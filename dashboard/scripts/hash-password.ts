/*
 * Genera un hash argon2id de la contraseña recibida por stdin.
 *
 * Uso:
 *   echo "mi-password-segura" | npx tsx scripts/hash-password.ts
 *   o
 *   npm run hash-password
 *   (entonces se pega la contraseña por stdin y se cierra con Ctrl-D)
 *
 * Imprime el hash listo para pegar en el SQL de creación del usuario:
 *
 *   INSERT INTO usuarios (id, email, nombre, password_hash, rol_global)
 *   VALUES (gen_random_uuid(), 'dani@birdcom.es', 'Dani Moreno',
 *           '<HASH_ARGON2>', 'superadmin');
 *
 * Parámetros argon2id (preset OWASP 2024):
 *   memoryCost: 19456 KiB · timeCost: 2 · parallelism: 1
 */

import argon2 from "argon2";
import readline from "node:readline";

const rl = readline.createInterface({
  input: process.stdin,
  terminal: false,
});

let received = false;

rl.on("line", async (password) => {
  received = true;
  rl.close();
  if (!password) {
    console.error("Error: contraseña vacía");
    process.exit(1);
  }
  try {
    const hash = await argon2.hash(password, {
      type: argon2.argon2id,
      memoryCost: 19456,
      timeCost: 2,
      parallelism: 1,
    });
    console.log(hash);
  } catch (err) {
    console.error(`Error al hashear: ${(err as Error).message}`);
    process.exit(1);
  }
});

rl.on("close", () => {
  if (!received) {
    console.error("Error: no se recibió contraseña por stdin");
    process.exit(1);
  }
});
