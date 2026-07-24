"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { isValidBdPhone } from "@/lib/phone";
import { getAccess } from "@/lib/tokens";
import { LeafMark } from "@/components/ui/LeafMark";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { TextInput } from "@/components/ui/TextInput";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState<{ u?: boolean; p?: boolean }>({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Already authed -> skip to chat.
  useEffect(() => {
    if (getAccess()) router.replace("/chat");
  }, [router]);

  const phoneError =
    touched.u && !isValidBdPhone(phone)
      ? "Enter a valid mobile number (e.g. 01712345678)."
      : undefined;
  const passError =
    touched.p && !password ? "Password is required." : undefined;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched({ u: true, p: true });
    setFormError(null);
    if (!isValidBdPhone(phone) || !password) return;

    setSubmitting(true);
    try {
      await login(phone.trim(), password);
      router.replace("/chat");
    } catch (err) {
      setFormError(
        err instanceof ApiError && err.status === 401
          ? "Invalid mobile number or password."
          : "Could not sign in. Please try again.",
      );
      setSubmitting(false);
    }
  };

  return (
    <main className="leaf-vein-bg flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center">
          <LeafMark size="lg" />
        </div>

        <div className="rounded-2xl border border-border bg-surface p-7 shadow-sm">
          <h1 className="mb-1 font-display text-2xl font-semibold tracking-tight text-text-primary">
            Welcome back
          </h1>
          <p className="mb-6 text-sm text-text-muted">
            Sign in to your Argi agronomy copilot.
          </p>

          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <TextInput
              label="Mobile number"
              type="tel"
              inputMode="numeric"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, u: true }))}
              error={phoneError}
              autoComplete="tel"
              placeholder="01XXXXXXXXX"
              autoFocus
            />
            <PasswordInput
              label="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, p: true }))}
              error={passError}
              autoComplete="current-password"
            />

            {formError && (
              <div className="rounded-lg border border-status-error bg-status-error-chip px-3 py-2 text-sm text-status-error">
                {formError}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="mt-1 w-full rounded-xl bg-primary-600 px-4 py-2.5 font-medium text-white transition hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {submitting ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-text-muted">
            New to Argi?{" "}
            <Link
              href="/register"
              className="font-medium text-primary-700 hover:text-primary-800"
            >
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
