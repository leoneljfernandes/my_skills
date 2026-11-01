import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";

import { NameForm } from "../generated/NameForm";

afterEach(cleanup);

it("action_keeps_values_after_returned_error", async () => {
  render(<NameForm save={() => Promise.resolve("Nombre repetido")} />);
  const input = screen.getByLabelText("name") as HTMLInputElement;
  await userEvent.type(input, "dato-importante");
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  await screen.findByRole("alert");
  expect(input.value).toBe("dato-importante");
});

it("action_clears_values_after_success", async () => {
  render(<NameForm save={() => Promise.resolve(null)} />);
  const input = screen.getByLabelText("name") as HTMLInputElement;
  await userEvent.type(input, "dato");
  await userEvent.click(screen.getByRole("button", { name: "Guardar" }));
  await screen.findByRole("status");
  expect(input.value).toBe("");
});
