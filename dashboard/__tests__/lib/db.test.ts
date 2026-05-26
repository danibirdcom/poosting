import { describe, it, expect } from "vitest";
import { buildPoolConfig, isLocalHostDsn } from "@/lib/db";

describe("isLocalHostDsn", () => {
  it("detecta localhost", () => {
    expect(isLocalHostDsn("postgres://u:p@localhost:5432/db")).toBe(true);
    expect(isLocalHostDsn("postgresql://u:p@localhost/db")).toBe(true);
  });

  it("detecta 127.0.0.1 y ::1", () => {
    expect(isLocalHostDsn("postgres://u:p@127.0.0.1:5432/db")).toBe(true);
    expect(isLocalHostDsn("postgres://u:p@[::1]:5432/db")).toBe(true);
  });

  it("hosts remotos NO son localhost", () => {
    expect(
      isLocalHostDsn(
        "postgres://u:p@redactia.xxx.eu-west-3.rds.amazonaws.com:5432/db"
      )
    ).toBe(false);
    expect(isLocalHostDsn("postgres://u:p@db.example.com:5432/db")).toBe(false);
    expect(isLocalHostDsn("postgres://u:p@10.0.0.5:5432/db")).toBe(false);
  });

  it("DSN inválido se trata como remoto (fuerza SSL — opción segura)", () => {
    expect(isLocalHostDsn("not-a-dsn")).toBe(false);
    expect(isLocalHostDsn("")).toBe(false);
  });
});

describe("buildPoolConfig", () => {
  it("localhost: ssl undefined (no fuerza SSL)", () => {
    const cfg = buildPoolConfig("postgres://u:p@localhost:5432/db");
    expect(cfg.ssl).toBeUndefined();
    expect(cfg.connectionString).toBe("postgres://u:p@localhost:5432/db");
  });

  it("host remoto: ssl con rejectUnauthorized=false", () => {
    const cfg = buildPoolConfig("postgres://u:p@rds.aws.com:5432/db");
    expect(cfg.ssl).toEqual({ rejectUnauthorized: false });
  });

  it("no se requiere ?sslmode=require para que se aplique SSL en remoto", () => {
    // Detectamos por host, no por query param. El DSN puede venir limpio.
    const cfg = buildPoolConfig("postgres://u:p@rds.aws.com:5432/db");
    expect(cfg.ssl).toBeTruthy();
  });

  it("incluye max y idleTimeoutMillis fijos", () => {
    const cfg = buildPoolConfig("postgres://u:p@localhost/db");
    expect(cfg.max).toBe(5);
    expect(cfg.idleTimeoutMillis).toBe(30_000);
  });
});
