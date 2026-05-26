import { redirect } from "next/navigation";

// El middleware decide a dónde mandar /: a /bandeja si hay sesión, a
// /login si no. Si por algún motivo llegas aquí, vamos a /login.
export default function HomePage() {
  redirect("/login");
}
