import { redirect } from "next/navigation";

// La home redirige a la bandeja (única pantalla útil en PR1).
export default function HomePage() {
  redirect("/bandeja");
}
