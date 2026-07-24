"use client";

import { ArrowLeft, LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { formatBdPhone } from "@/lib/phone";
import { getAccess } from "@/lib/tokens";
import { LeafMark } from "@/components/ui/LeafMark";

function Field({
  label,
  value,
  code,
}: {
  label: string;
  value: string;
  code?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border py-3 last:border-b-0">
      <span className="text-sm text-text-muted">{label}</span>
      <span className="flex items-center gap-2 text-right">
        <span className="font-medium text-text-primary">{value || "—"}</span>
        {code && (
          <span className="rounded-md bg-primary-50 px-1.5 py-0.5 font-mono text-xs text-primary-700">
            {code}
          </span>
        )}
      </span>
    </div>
  );
}

export default function ProfilePage() {
  const router = useRouter();
  const { user, loading, logout } = useAuth();

  useEffect(() => {
    if (!getAccess()) router.replace("/login");
  }, [router]);

  if (loading || !user) {
    return (
      <div className="flex h-screen items-center justify-center bg-background text-text-muted">
        Loading…
      </div>
    );
  }

  const a = user.address;

  return (
    <main className="leaf-vein-bg min-h-screen bg-background px-4 py-10">
      <div className="mx-auto w-full max-w-md">
        <div className="mb-6 flex items-center justify-between">
          <Link
            href="/chat"
            className="flex items-center gap-1.5 text-sm font-medium text-primary-700 hover:text-primary-800"
          >
            <ArrowLeft size={16} strokeWidth={1.75} />
            Back to chat
          </Link>
          <LeafMark size="sm" />
        </div>

        <div className="rounded-2xl border border-border bg-surface p-7 shadow-sm">
          <h1 className="mb-1 font-display text-2xl font-semibold tracking-tight text-text-primary">
            {user.username}
          </h1>
          <p className="mb-6 text-sm text-text-muted">
            {formatBdPhone(user.phone)}
          </p>

          <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Account
          </h2>
          <div className="mb-5">
            <Field label="Name" value={user.username} />
            <Field label="Mobile number" value={formatBdPhone(user.phone)} />
          </div>

          <h2 className="mb-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
            Location
          </h2>
          <div className="mb-6">
            <Field
              label="Division"
              value={a.division_name}
              code={a.division_code}
            />
            <Field
              label="District"
              value={a.district_name}
              code={a.district_code}
            />
            <Field
              label="Upazila"
              value={a.upazila_name}
              code={a.upazila_code}
            />
          </div>

          <button
            type="button"
            onClick={() => logout()}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-border px-4 py-2.5 text-sm font-medium text-text-primary transition hover:bg-primary-50"
          >
            <LogOut size={16} strokeWidth={1.75} className="text-primary-600" />
            Log out
          </button>
        </div>
      </div>
    </main>
  );
}
