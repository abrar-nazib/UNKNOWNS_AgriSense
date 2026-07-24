"use client";

import {
  Loader2,
  ShieldCheck,
  Smartphone,
  X,
} from "lucide-react";
import { useState } from "react";
import {
  apiRequestBillingOtp,
  apiVerifyBillingOtp,
} from "@/lib/api";
import { formatBdPhone } from "@/lib/phone";
import type { Subscription } from "@/lib/types";

type Step = "confirm" | "otp" | "processing";

interface Props {
  planId: "plus" | "pro";
  tierName: string;
  amount: number;
  mobile: string;
  provider: "mock" | "bdapps";
  onClose: () => void;
  onSuccess: (subscription: Subscription) => void;
}

const row = "flex justify-between gap-4 py-1";

export function BdAppsCheckout({
  planId,
  tierName,
  amount,
  mobile,
  provider,
  onClose,
  onSuccess,
}: Props) {
  const [step, setStep] = useState<Step>("confirm");
  const [busy, setBusy] = useState(false);
  const [challengeId, setChallengeId] = useState("");
  const [demoOtp, setDemoOtp] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [err, setErr] = useState("");

  const sendOtp = async () => {
    setBusy(true);
    setErr("");
    try {
      const result = await apiRequestBillingOtp(planId);
      setChallengeId(result.challenge_id);
      setDemoOtp(result.demo_otp);
      setStep("otp");
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not send OTP.");
    } finally {
      setBusy(false);
    }
  };

  const confirmSubscription = async () => {
    setBusy(true);
    setErr("");
    setStep("processing");
    try {
      const result = await apiVerifyBillingOtp(challengeId, otp);
      onSuccess(result);
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Could not verify OTP.");
      setStep("otp");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm overflow-hidden border border-jute-300/70 bg-surface shadow-2xl">
        <div className="flex items-center justify-between border-b border-jute-300/55 bg-paper-100 px-4 py-3">
          <span className="flex items-center gap-2 text-sm font-semibold text-text-primary">
            <ShieldCheck size={16} className="text-primary-600" />
            {provider === "bdapps"
              ? "Subscribe with BDApps"
              : "Development subscription"}
          </span>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
            className="rounded-full p-1 text-text-muted transition hover:-translate-y-0.5 hover:bg-paper-50 hover:text-text-primary hover:shadow-card disabled:cursor-not-allowed disabled:opacity-40"
          >
            <X size={18} />
          </button>
        </div>

        <div className="p-5">
          {step === "confirm" && (
            <div className="space-y-4">
              <div className="border border-jute-300/60 p-3 text-sm">
                <div className={row}>
                  <span className="text-text-muted">Plan</span>
                  <span className="font-medium text-text-primary">
                    AgriSense {tierName}
                  </span>
                </div>
                <div className={row}>
                  <span className="text-text-muted">Subscription</span>
                  <span className="nums font-semibold text-text-primary">
                    ৳{amount}/month
                  </span>
                </div>
                <div className={row}>
                  <span className="text-text-muted">Mobile</span>
                  <span className="nums font-medium text-text-primary">
                    {formatBdPhone(mobile)}
                  </span>
                </div>
              </div>
              {provider === "bdapps" ? (
                <p className="text-xs leading-relaxed text-text-muted">
                  By verifying the OTP, you authorize a recurring ৳{amount}
                  monthly charge to this Robi number. The subscription activates
                  immediately and can be cancelled from this page.
                </p>
              ) : (
                <p className="text-xs text-text-muted">
                  This local development flow uses OTP 1234 and does not charge
                  your mobile account.
                </p>
              )}
              {err && <p className="text-xs text-status-error">{err}</p>}
              <button
                type="button"
                onClick={sendOtp}
                disabled={busy}
                className="atlas-button w-full disabled:opacity-60"
              >
                {busy ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Smartphone size={15} />
                )}
                Send OTP
              </button>
            </div>
          )}

          {step === "otp" && (
            <div className="space-y-4">
              <p className="text-sm text-text-primary">
                Enter the code sent to {formatBdPhone(mobile)}.
              </p>
              {provider === "bdapps" && (
                <p className="text-xs leading-relaxed text-text-muted">
                  Successful verification immediately activates the recurring
                  ৳{amount}/month subscription.
                </p>
              )}
              {demoOtp && (
                <p className="border border-jute-300 bg-jute-100 px-3 py-2 font-mono text-xs text-field-900">
                  Development OTP:{" "}
                  <span className="nums font-semibold tracking-widest">
                    {demoOtp}
                  </span>
                </p>
              )}
              <input
                inputMode="numeric"
                maxLength={8}
                value={otp}
                onChange={(event) =>
                  setOtp(event.target.value.replace(/\D/g, ""))
                }
                placeholder="Enter OTP"
                className="nums min-h-12 w-full rounded-lg border border-jute-300/70 bg-paper-50 px-3.5 py-2.5 text-center font-mono text-lg tracking-[0.4em] outline-none transition focus:border-clay-400 focus:ring-0 focus:shadow-[0_8px_24px_-18px_rgba(23,38,28,0.55)]"
              />
              {err && <p className="text-xs text-status-error">{err}</p>}
              <button
                type="button"
                onClick={confirmSubscription}
                disabled={busy || otp.length < 4}
                className="atlas-button w-full disabled:opacity-60"
              >
                {busy && <Loader2 size={15} className="animate-spin" />}
                {provider === "bdapps"
                  ? `Verify & activate ৳${amount}/month`
                  : "Verify development OTP"}
              </button>
            </div>
          )}

          {step === "processing" && (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <Loader2 size={28} className="animate-spin text-primary-600" />
              <p className="text-sm text-text-muted">
                Verifying OTP and activating your subscription…
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
