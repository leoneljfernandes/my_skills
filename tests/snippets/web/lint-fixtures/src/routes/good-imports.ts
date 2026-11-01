import { ordersApi } from "@/features/orders";
import { http } from "@/lib/http";
import { Button } from "@/components/Button";
import { loader } from "./load-error";
export const ok = [ordersApi, http, Button, loader];
