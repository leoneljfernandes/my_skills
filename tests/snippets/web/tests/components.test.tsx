// Componentes de routing, actions y api.ts de las skills, probados uno a uno.
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, expect, it, vi } from "vitest";

import { DefaultFallback, ErrorBoundary } from "@/components/ErrorBoundary";
import { ordersApi } from "@/features/orders";
import { productsApi } from "@/features/products";
import { ProductStock } from "@/features/products/ProductStock";
import { http } from "@/lib/http";
import type { ActionResult } from "@/lib/action-result";
import { setErrorReporter } from "@/lib/telemetry";
import { NotifyButton } from "@/routes/notify";
import { NewProductForm } from "@/routes/list-forms";
import { RouteError } from "@/routes/route-error";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// --- FE-03: el alta con useFetcher ---

it("NewProductForm: vacía el form una vez por resultado; escribir y re-renderizar el padre conserva lo escrito", async () => {
  const action = vi.fn(() => ({ status: "success", data: null }) satisfies ActionResult);
  let bump!: () => void;
  function Page(): ReactNode {
    const [renders, setRenders] = useState(0);
    bump = () => setRenders((n) => n + 1);
    return (
      <>
        <p>renders {renders}</p>
        <NewProductForm />
      </>
    );
  }
  render(<RouterProvider router={createMemoryRouter([{ path: "/", Component: Page, action }])} />);
  const field = () => screen.getByRole("textbox") as HTMLInputElement;

  await userEvent.type(field(), "uno");
  await userEvent.click(screen.getByRole("button", { name: "Agregar" }));
  await waitFor(() => expect(field().value).toBe("")); // alta con éxito: formulario vacío

  // fireEvent y no userEvent: user-event lleva su propia cuenta del valor y no se entera de un form.reset().
  fireEvent.change(field(), { target: { value: "dos" } });
  act(() => bump()); // el padre se re-renderiza mientras se escribe el siguiente registro
  await screen.findByText("renders 1");
  expect(field().value).toBe("dos");
  expect(action).toHaveBeenCalledTimes(1);
});

it("NewProductForm: deshabilita el botón mientras guarda y muestra el error esperable", async () => {
  let release!: () => void;
  const action = () =>
    new Promise<ActionResult>((resolve) => {
      release = () => resolve({ status: "error", message: "Nombre repetido", fieldErrors: {}, values: {} });
    });
  render(<RouterProvider router={createMemoryRouter([{ path: "/", Component: NewProductForm, action }])} />);

  await userEvent.type(screen.getByRole("textbox"), "taza");
  await userEvent.click(screen.getByRole("button", { name: "Agregar" }));
  const busy = await screen.findByRole("button", { name: "Agregando…" });
  expect((busy as HTMLButtonElement).disabled).toBe(true);
  expect(busy.getAttribute("aria-busy")).toBe("true");

  await act(async () => release());
  expect((await screen.findByRole("alert")).textContent).toBe("Nombre repetido");
  expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("taza"); // fetcher.Form conserva
});

// --- FE-14 ---

it("NotifyButton: un rechazo llega a la boundary de la ruta y a onError (no queda mudo)", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.spyOn(ordersApi, "notify").mockRejectedValue(new Error("boom-notify"));
  const onError = vi.fn();
  const router = createMemoryRouter([
    { path: "/", element: <NotifyButton orderId={7} />, ErrorBoundary: RouteError },
  ]);
  render(<RouterProvider router={router} onError={onError} />);

  await userEvent.click(screen.getByRole("button", { name: "Notificar" }));

  await screen.findByText("Error inesperado");
  expect(onError).toHaveBeenCalledTimes(1);
  expect(onError.mock.calls[0]?.[0]).toMatchObject({ message: "boom-notify" });
});

it("NotifyButton: mientras notifica está deshabilitado y al terminar revalida", async () => {
  let release!: () => void;
  vi.spyOn(ordersApi, "notify").mockImplementation(() => new Promise<void>((resolve) => (release = resolve)));
  const loader = vi.fn(() => null);
  const router = createMemoryRouter([{ path: "/", element: <NotifyButton orderId={7} />, loader }]);
  render(<RouterProvider router={router} />);
  await waitFor(() => expect(loader).toHaveBeenCalledTimes(1));

  await userEvent.click(screen.getByRole("button", { name: "Notificar" }));
  expect((screen.getByRole("button", { name: "Notificar" }) as HTMLButtonElement).disabled).toBe(true);

  await act(async () => release());
  await waitFor(() => expect(loader).toHaveBeenCalledTimes(2)); // revalidate()
  await waitFor(() => expect((screen.getByRole("button", { name: "Notificar" }) as HTMLButtonElement).disabled).toBe(false));
});

// --- FE-10 ---

it("ProductStock: 'Reintentar' crea una promesa nueva y recupera el widget", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  setErrorReporter(() => undefined);
  const getProduct = vi
    .spyOn(productsApi, "getProduct")
    .mockRejectedValueOnce(new Error("404"))
    .mockResolvedValue({ id: 7, name: "Taza", stock: 5 });
  await act(async () => void render(<ProductStock productId={7} />)); // render async: el componente suspende

  await screen.findByText("Algo salió mal en esta sección.");
  await act(async () => {
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" })); // remonta y suspende de nuevo
  });

  expect((await screen.findByText("5 unidades")).textContent).toBe("5 unidades");
  expect(getProduct).toHaveBeenCalledTimes(2); // un request nuevo, no el rechazo memoizado
});

it("ProductStock: cambiar de producto pide el nuevo stock", async () => {
  vi.spyOn(productsApi, "getProduct").mockImplementation((id) => Promise.resolve({ id, name: "x", stock: id * 10 }));
  let view!: ReturnType<typeof render>;
  await act(async () => void (view = render(<ProductStock productId={1} />)));
  await screen.findByText("10 unidades");
  await act(async () => view.rerender(<ProductStock productId={2} />));
  await screen.findByText("20 unidades");
});

// --- FE-22: las lecturas pasan el signal; las mutaciones no lo aceptan ---

it("lecturas de api.ts: el signal llega a la request; searchProducts manda q", async () => {
  const seen: { url: string | undefined; signal: unknown; params: unknown }[] = [];
  http.defaults.adapter = (config) => {
    seen.push({ url: config.url, signal: config.signal, params: config.params });
    return Promise.resolve({ status: 200, statusText: "", headers: {}, config, data: config.url === "/products" ? { items: [] } : { id: 1 } });
  };
  const controller = new AbortController();

  await productsApi.getProduct(1, { signal: controller.signal });
  await productsApi.searchProducts("taza", { signal: controller.signal });

  expect(seen.map((r) => r.signal)).toEqual([controller.signal, controller.signal]);
  expect(seen[1]?.params).toEqual({ q: "taza" });
  // placeOrder(input) no tiene segundo parámetro: abortar un POST no deshace la orden (ver la skill).
  expect(ordersApi.placeOrder.length).toBe(1);
});

// --- el ErrorBoundary de components sigue recuperándose con resetKeys (base de FE-10) ---

it("ErrorBoundary: onReset se llama al reintentar", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  setErrorReporter(() => undefined);
  const onReset = vi.fn();
  function Boom(): ReactNode {
    throw new Error("x");
  }
  render(
    <ErrorBoundary scope="t" fallback={DefaultFallback} onReset={onReset}>
      <Boom />
    </ErrorBoundary>,
  );
  await userEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
  expect(onReset).toHaveBeenCalledTimes(1);
});

// --- FE-09, FE-01: qué hace rethrowAsRouteError con cada kind ---

import { ApiRequestError, type ApiError } from "@/lib/http/errors";
import { rethrowAsRouteError } from "@/routes/load-error";

function thrownBy(kind: ApiError): unknown {
  try {
    rethrowAsRouteError(new ApiRequestError(kind), new Request("http://localhost/products/7?x=1"));
  } catch (thrown) {
    return thrown;
  }
  return undefined;
}

it("rethrowAsRouteError: not_found y forbidden son respuestas de ruta; unauthorized, un redirect al login con el destino", () => {
  expect(thrownBy({ kind: "not_found", problem: null })).toMatchObject({ type: "DataWithResponseInit", init: { status: 404 } });
  expect(thrownBy({ kind: "forbidden", problem: null })).toMatchObject({ type: "DataWithResponseInit", init: { status: 403 } });
  const redirect = thrownBy({ kind: "unauthorized", problem: null });
  expect(redirect).toBeInstanceOf(Response);
  expect((redirect as Response).headers.get("Location")).toBe("/login?next=%2Fproducts%2F7%3Fx%3D1");
});

it("rethrowAsRouteError: canceled y lo inesperado se relanzan tal cual (boundary + telemetría)", () => {
  const canceled = new ApiRequestError({ kind: "canceled" });
  expect(() => rethrowAsRouteError(canceled, new Request("http://localhost/"))).toThrow(canceled);
  const server = new ApiRequestError({ kind: "server", status: 500, problem: null });
  expect(() => rethrowAsRouteError(server, new Request("http://localhost/"))).toThrow(server);
  const plain = new Error("boom");
  expect(() => rethrowAsRouteError(plain, new Request("http://localhost/"))).toThrow(plain);
});
