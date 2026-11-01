import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { ordersApi, QuickOrderForm } from "@/features/orders";

import { ApiRequestError } from "../generated/lib/http/errors";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const product = { id: 7, name: "Taza", stock: 5 };

it("quick_order_reports_success_and_calls_parent", async () => {
  const onOrdered = vi.fn();
  vi.spyOn(ordersApi, "placeOrder").mockResolvedValue({ id: 7 });
  render(<QuickOrderForm product={product} customerEmail="a@b.com" onOrdered={onOrdered} />);
  await userEvent.click(screen.getByRole("button", { name: "Comprar" }));
  expect((await screen.findByRole("status")).textContent).toBe("Orden #7 creada");
  expect(onOrdered).toHaveBeenCalledWith({ id: 7 });
});

it("quick_order_keeps_typed_quantity_after_validation_error", async () => {
  const failure = new ApiRequestError({
    kind: "validation",
    problem: { title: "x", status: 422, code: "validation_error", detail: "Cantidad inválida" },
    fieldErrors: { quantity: "Máximo 5" },
  });
  vi.spyOn(ordersApi, "placeOrder").mockRejectedValue(failure);
  render(<QuickOrderForm product={product} customerEmail="a@b.com" onOrdered={() => undefined} />);
  const input = screen.getByLabelText("Cantidad") as HTMLInputElement;
  await userEvent.clear(input);
  await userEvent.type(input, "4");
  await userEvent.click(screen.getByRole("button", { name: "Comprar" }));
  expect((await screen.findByRole("alert")).textContent).toBe("Máximo 5");
  expect(input.value).toBe("4");
});
