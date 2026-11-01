import { router } from "@/routes/root-layout";
import { requireUser } from "@/features/auth";
export const ok = [router, requireUser];
