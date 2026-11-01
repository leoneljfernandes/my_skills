import { productsApi } from "@/features/products";
import { isApiRequestError } from "@/lib/http/errors";
import { ordersApi } from "./api";
export const ok = [productsApi, isApiRequestError, ordersApi];
