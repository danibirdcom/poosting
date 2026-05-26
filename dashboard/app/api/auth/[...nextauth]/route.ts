import { handlers } from "@/auth";

// NextAuth v5: exporta handlers.GET y handlers.POST. Necesita Node runtime
// porque auth.ts importa argon2 y pg.
export const { GET, POST } = handlers;
export const runtime = "nodejs";
