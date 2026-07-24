"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { isValidBdPhone } from "@/lib/phone";
import { getAccess } from "@/lib/tokens";
import type { Address } from "@/lib/types";
import { AddressPicker, EMPTY_ADDRESS } from "@/components/address/AddressPicker";
import { LeafMark } from "@/components/ui/LeafMark";
import { PasswordInput } from "@/components/ui/PasswordInput";
import { TextInput } from "@/components/ui/TextInput";

export default function RegisterPage() {
  const router = useRouter();
  const { register, login } = useAuth();

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password1, setPassword1] = useState("");
  const [password2, setPassword2] = useState("");
  const [address, setAddress] = useState<Address>(EMPTY_ADDRESS);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (getAccess()) router.replace("/chat");
  }, [router]);

  const mark = (k: string) => setTouched((t) => ({ ...t, [k]: true }));

  const addressComplete = Boolean(
    address.division_code && address.district_code && address.upazila_code,
  );

  const errors = {
    name: touched.name && !name.trim() ? "Your name is required." : undefined,
    phone:
      touched.phone && !isValidBdPhone(phone)
        ? "Enter a valid mobile number (e.g. 01712345678)."
        : undefined,
    password1:
      touched.password1 && password1.length < 8
        ? "Password must be at least 8 characters."
        : undefined,
    password2:
      touched.password2 && password2 !== password1
        ? "Passwords do not match."
        : undefined,
    address:
      touched.address && !addressComplete
        ? "Select your division, district and upazila."
        : undefined,
  };

  const valid =
    name.trim() &&
    isValidBdPhone(phone) &&
    password1.length >= 8 &&
    password1 === password2 &&
    addressComplete;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched({
      name: true,
      phone: true,
      password1: true,
      password2: true,
      address: true,
    });
    setFormError(null);
    if (!valid) return;

    setSubmitting(true);
    try {
      await register({
        username: name.trim(),
        phone: phone.trim(),
        password1,
        password2,
        ...address,
      });
      // Auto-login on success, then head to chat. Falls back to /login.
      try {
        await login(phone.trim(), password1);
        router.replace("/chat");
      } catch {
        router.replace("/login");
      }
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message || "Could not create account."
          : "Could not create account. Please try again.",
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
            Create your account
          </h1>
          <p className="mb-6 text-sm text-text-muted">
            Start growing with your Argi copilot.
          </p>

          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <TextInput
              label="Your name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => mark("name")}
              error={errors.name}
              autoComplete="name"
              autoFocus
            />
            <TextInput
              label="Mobile number"
              type="tel"
              inputMode="numeric"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              onBlur={() => mark("phone")}
              error={errors.phone}
              autoComplete="tel"
              placeholder="01XXXXXXXXX"
            />

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-text-primary">
                Your location
              </span>
              <AddressPicker
                value={address}
                onChange={setAddress}
                onBlur={() => mark("address")}
                error={errors.address}
              />
            </div>

            <PasswordInput
              label="Password"
              value={password1}
              onChange={(e) => setPassword1(e.target.value)}
              onBlur={() => mark("password1")}
              error={errors.password1}
              autoComplete="new-password"
            />
            <PasswordInput
              label="Confirm password"
              value={password2}
              onChange={(e) => setPassword2(e.target.value)}
              onBlur={() => mark("password2")}
              error={errors.password2}
              autoComplete="new-password"
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
              {submitting ? "Creating account…" : "Create account"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-text-muted">
            Already have an account?{" "}
            <Link
              href="/login"
              className="font-medium text-primary-700 hover:text-primary-800"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
