// La app publicada en las skills (router, sesión, login, actions, boundaries) corriendo en jsdom.
// Límite: jsdom no reproduce la carrera real entre una navegación y la respuesta 401 (FE-01); esa
// parte se comprueba en un navegador.
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider } from "react-router/dom";
import { afterEach, expect, it, vi } from "vitest";

import { bootApp, isUrl, ME, problem, publishedOnError } from "./helpers/app";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const reports: unknown[][] = [];
async function mount(url: string, handler: Parameters<typeof bootApp>[1]) {
  reports.length = 0;
  const app = await bootApp(url, handler);
  const onError = await publishedOnError((error, context) => reports.push([error, context]));
  render(<RouterProvider router={app.router} onError={onError} />);
  return app;
}

const okMe = (config: Parameters<Parameters<typeof bootApp>[1]>[0]) => (isUrl(config, "/auth/me") ? { status: 200, data: ME } : null);

// --- FE-01 ---

it("session_expiry_next_keeps_target: al vencer la sesión navegando, el next es el destino", async () => {
  let authed = true;
  const { router } = await mount("/products", (c) =>
    okMe(c) ?? (authed ? { status: 200, data: { id: 7, name: "Taza", stock: 5 } } : { status: 401, data: problem(401, "not_authenticated") }),
  );
  await screen.findByText("products");
  expect(window.location.pathname).toBe("/products"); // durante la navegación seguirá siendo esta: la trampa del assign

  authed = false;
  await act(async () => {
    await router.navigate("/products/7?x=1");
  });

  await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  expect(router.state.location.search).toBe("?next=%2Fproducts%2F7%3Fx%3D1");
  expect(screen.queryByText("Error inesperado")).toBeNull();
  expect(reports).toEqual([]); // un 401 de sesión vencida no es un error de la app
});

it("primera visita sin sesión: va a /login con el next de la pantalla pedida", async () => {
  const { router } = await mount("/products?f=1", (c) => (isUrl(c, "/auth/me") ? { status: 401, data: problem(401, "not_authenticated") } : { status: 200 }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  expect(router.state.location.search).toBe("?next=%2Fproducts%3Ff%3D1");
});

// --- FE-16 ---

it("la compra tiene a dónde ir y el buscador no cae en :productId; el 404 queda dentro del layout", async () => {
  const { router } = await mount("/products", (c) => okMe(c) ?? { status: 200, data: [] });
  await screen.findByText("products");

  await act(async () => router.navigate("/orders/1"));
  await screen.findByText("order-detail");
  expect(screen.getByText("Productos")).toBeTruthy(); // la navegación del layout sigue

  await act(async () => router.navigate("/products/search?q=ab"));
  await waitFor(() => expect(router.state.location.pathname).toBe("/products/search"));
  expect(screen.queryByRole("alert")).toBeNull();

  await act(async () => router.navigate("/no/existe"));
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByText("No encontrado")).toBeTruthy();
  expect(screen.getByText("Productos")).toBeTruthy(); // 404 dentro del layout
  expect(alert.textContent).not.toContain("No route matches");
});

// --- FE-04 ---

async function submitLogin(email: string) {
  await userEvent.type(await screen.findByLabelText("Email"), email);
  await userEvent.type(screen.getByLabelText("Contraseña"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Ingresar" }));
}

it("login con contraseña mala: conserva el email y no va a la boundary", async () => {
  await mount("/login", (c) =>
    isUrl(c, "/auth/token") ? { status: 401, data: problem(401, "invalid_credentials", { detail: "Incorrect email or password" }) } : { status: 200, data: ME },
  );
  await submitLogin("ana@example.com");
  expect((await screen.findByRole("alert")).textContent).toBe("Email o contraseña incorrectos");
  expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("ana@example.com");
  expect(screen.queryByText("Error inesperado")).toBeNull();
  expect(reports).toEqual([]);
});

it("login con 429 (límite de intentos de nginx, HTML): avisa de esperar y conserva el email", async () => {
  await mount("/login", () => ({ status: 429, data: "<html>429</html>" }));
  await submitLogin("ana@example.com");
  expect((await screen.findByRole("alert")).textContent).toContain("Demasiados intentos");
  expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("ana@example.com");
  expect(reports).toEqual([]);
});

it("login correcto: vuelve al next validado (y descarta un next externo)", async () => {
  let logged = false;
  const { router } = await mount("/login?next=%2Fproducts%3Ff%3D1", (c) => {
    if (isUrl(c, "/auth/token")) {
      logged = true;
      return { status: 200, data: { access_token: "t" } };
    }
    return logged ? (okMe(c) ?? { status: 200 }) : { status: 401, data: problem(401, "not_authenticated") };
  });
  await submitLogin("ana@example.com");
  await waitFor(() => expect(router.state.location.pathname).toBe("/products"));
  expect(router.state.location.search).toBe("?f=1");
});

// --- FE-02, FE-09, FE-08: la action de product-detail ---

async function buy(handler: (c: Parameters<Parameters<typeof bootApp>[1]>[0]) => ReturnType<Parameters<typeof bootApp>[1]>) {
  await mount("/products/7", (c) => okMe(c) ?? (isUrl(c, "/orders") ? handler(c) : { status: 200, data: { id: 7, name: "Taza", stock: 5 } }));
  const quantity = (await screen.findByLabelText("Cantidad")) as HTMLInputElement;
  await userEvent.clear(quantity);
  await userEvent.type(quantity, "3");
  await userEvent.click(screen.getByRole("button", { name: "Comprar" }));
}

it("un 409 conserva el formulario y muestra el mensaje (no 'Error inesperado')", async () => {
  await buy(() => ({ status: 409, data: problem(409, "conflict", { detail: "Sin stock suficiente" }) }));
  expect((await screen.findByRole("alert")).textContent).toBe("Sin stock suficiente");
  expect((screen.getByLabelText("Cantidad") as HTMLInputElement).value).toBe("3");
  expect(reports).toEqual([]);
});

it("un 422 sin error de campo (regla de negocio) también se ve", async () => {
  await buy(() => ({ status: 422, data: problem(422, "business_rule_violated", { detail: "Producto descontinuado" }) }));
  expect((await screen.findByRole("alert")).textContent).toBe("Producto descontinuado");
  expect((screen.getByLabelText("Cantidad") as HTMLInputElement).value).toBe("3");
});

it("un 422 de Pydantic sobre otro campo muestra el mensaje genérico", async () => {
  await buy(() => ({
    status: 422,
    data: problem(422, "validation_error", { errors: [{ type: "missing", loc: ["body", "customer_email"], msg: "Field required" }] }),
  }));
  expect((await screen.findByRole("alert")).textContent).toBe("Revisá los datos");
});

it("sin conexión: aviso junto al form y lo escrito se conserva", async () => {
  await buy(() => ({ status: 0, network: true }));
  expect((await screen.findByRole("alert")).textContent).toBe("Sin conexión. Probá de nuevo.");
  expect((screen.getByLabelText("Cantidad") as HTMLInputElement).value).toBe("3");
});

it.each([
  [403, "permission_denied", "Error 403"],
  [404, "not_found", "No encontrado"],
])("action con %i: respuesta de ruta, igual que en un loader, y no se reporta (FE-09, FE-08)", async (status, code, heading) => {
  await buy(() => ({ status, data: problem(status, code) }));
  expect((await screen.findByRole("heading", { name: heading })).textContent).toBe(heading);
  expect(screen.queryByText("Error inesperado")).toBeNull();
  expect(reports).toEqual([]); // 404/403 de ruta: se muestran, no se reportan
});

it("un 500 sí es inesperado: boundary + un reporte con el trace_id", async () => {
  await buy(() => ({ status: 500, data: problem(500, "internal_error") }));
  await screen.findByText("Error inesperado");
  expect(reports).toHaveLength(1);
  expect(reports[0]?.[0]).toMatchObject({ traceId: "trace-500" });
});

it("compra correcta: redirige a /orders/:id", async () => {
  const { router } = await mount("/products/7", (c) =>
    okMe(c) ?? (isUrl(c, "/orders") ? { status: 201, data: { id: 42 } } : { status: 200, data: { id: 7, name: "Taza", stock: 5 } }),
  );
  await userEvent.click(await screen.findByRole("button", { name: "Comprar" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/orders/42"));
});

// --- FE-08: el onError publicado ---

it("onRouterError: ni un 404 ni un 403 de ruta se reportan; un error inesperado sí, una vez", async () => {
  const { onRouterError } = await import("@/on-router-error");
  const { UNSAFE_ErrorResponseImpl: RouteResponse } = await import("react-router"); // lo que el router entrega a onError
  const reporter = vi.fn();
  (await import("@/lib/telemetry")).setErrorReporter(reporter);
  const info = { location: { pathname: "/x" }, pattern: "/x" } as never;

  onRouterError(new RouteResponse(404, "Not Found", "x"), info);
  onRouterError(new RouteResponse(403, "Forbidden", "x"), info);
  expect(reporter).not.toHaveBeenCalled();

  onRouterError(new Error("boom"), info);
  expect(reporter).toHaveBeenCalledTimes(1);
});

// --- FE-20 ---

it("Reintentar en RouteError vuelve a correr el loader y recupera la ruta", async () => {
  let failing = true;
  await mount("/products/7", (c) =>
    okMe(c) ?? (failing ? { status: 500, data: problem(500, "internal_error") } : { status: 200, data: { id: 7, name: "Taza", stock: 5 } }),
  );
  await screen.findByText("Error inesperado");
  failing = false;
  await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
  expect((await screen.findByRole("heading", { name: "Taza" })).textContent).toBe("Taza");
  expect(screen.queryByText("Error inesperado")).toBeNull();
});
