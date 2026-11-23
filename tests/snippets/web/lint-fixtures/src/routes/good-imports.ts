import { ordersApi } from "@/features/orders";
import { currentUser } from "@/features/auth";
import { Button } from "@/components/Button";
import { loader } from "./load-error";
export const ok = [ordersApi, currentUser, Button, loader];
