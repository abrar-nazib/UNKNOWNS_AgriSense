"use client";

import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Check,
  CreditCard,
  History,
  LogOut,
  MessageSquare,
  Sprout,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { BdAppsCheckout } from "@/components/billing/BdAppsCheckout";
import { LeafMark } from "@/components/ui/LeafMark";
import {
  apiBillingPlans,
  apiCancelSubscription,
  apiChangePassword,
  apiSubscription,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useChat } from "@/lib/chat/ChatProvider";
import { useSessions } from "@/lib/hooks";
import { formatBdPhone } from "@/lib/phone";
import { getAccess } from "@/lib/tokens";
import type {
  BillingPlansResponse,
  Session,
  Subscription,
} from "@/lib/types";

type ProfileTab = "info" | "history" | "billing";

function parseProfileTab(value: string | null): ProfileTab {
  return value === "history" || value === "billing" ? value : "info";
}

const TIERS = [
  {
    id: "free",
    name: "Free",
    price: "৳0",
    tagline: "For trying it out",
    features: ["Standard model", "Core plan, weather & crop advice", "Saved chat history"],
  },
  {
    id: "plus",
    name: "Plus",
    price: "৳199/mo",
    tagline: "For active farmers",
    features: ["Faster model", "Deeper reasoning steps", "Priority weather refresh", "Scenario what-ifs"],
  },
  {
    id: "pro",
    name: "Pro",
    price: "৳499/mo",
    tagline: "For agri-entrepreneurs",
    features: ["Best model + longest thinking", "Leaf-photo disease detection", "Market price alerts", "BDApps payments"],
  },
] as const;

type TierId = (typeof TIERS)[number]["id"];
type PaidTierId = Exclude<TierId, "free">;
const RANK: Record<TierId, number> = { free: 0, plus: 1, pro: 2 };
const PRICE: Record<TierId, number> = { free: 0, plus: 199, pro: 499 };

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="atlas-panel p-3 text-center transition duration-300 hover:-translate-y-1 hover:shadow-lift">
      <p className="font-mono text-[10px] uppercase tracking-wide text-text-muted">{label}</p>
      <p className="nums mt-0.5 font-display text-lg font-semibold text-text-primary">{value}</p>
    </div>
  );
}

// --------------------------------------------------------------------------- //
export default function ProfilePage() {
  return (
    <Suspense fallback={<ProfileLoading />}>
      <ProfileContent />
    </Suspense>
  );
}

function ProfileLoading() {
  return (
    <div className="atlas-grid flex h-screen items-center justify-center text-ink-500">
      Opening your field ledger…
    </div>
  );
}

function ProfileContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading, logout } = useAuth();
  const activeTab = parseProfileTab(searchParams.get("tab"));
  const [tier, setTier] = useState<TierId>("free");
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [serverPrices, setServerPrices] = useState<Record<string, number>>({});
  const [billingProvider, setBillingProvider] =
    useState<BillingPlansResponse["provider"]>("mock");
  const [subscribablePlanIds, setSubscribablePlanIds] = useState<
    Array<"plus" | "pro">
  >(["plus", "pro"]);
  const [billingBusy, setBillingBusy] = useState(false);
  const [billingMsg, setBillingMsg] = useState("");
  const [checkout, setCheckout] = useState<{
    id: PaidTierId;
    name: string;
    amount: number;
  } | null>(null);

  useEffect(() => {
    if (!getAccess()) {
      router.replace("/login");
      return;
    }
    let active = true;
    Promise.all([apiSubscription(), apiBillingPlans()])
      .then(([current, catalog]) => {
        if (!active) return;
        setSubscription(current);
        setTier(
          current.status === "active" && current.plan_id in RANK
            ? current.plan_id
            : "free",
        );
        setServerPrices(
          Object.fromEntries(
            catalog.results.map((plan) => [plan.id, plan.amount_bdt]),
          ),
        );
        setBillingProvider(catalog.provider);
        setSubscribablePlanIds(catalog.subscribable_plan_ids);
      })
      .catch((error) => {
        if (active) {
          setBillingMsg(
            error instanceof Error
              ? error.message
              : "Could not load subscription.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [router]);

  const cancelCurrentSubscription = async () => {
    setBillingBusy(true);
    setBillingMsg("");
    try {
      const result = await apiCancelSubscription();
      setSubscription(result.subscription);
      setTier("free");
      setBillingMsg(result.status_detail);
    } catch (error) {
      setBillingMsg(
        error instanceof Error ? error.message : "Could not cancel subscription.",
      );
    } finally {
      setBillingBusy(false);
    }
  };

  const selectTab = (tab: ProfileTab) => {
    const query = new URLSearchParams(searchParams.toString());
    query.set("tab", tab);
    router.replace(`/profile?${query.toString()}`, { scroll: false });
  };

  if (loading || !user) {
    return (
      <ProfileLoading />
    );
  }

  const tabs: { id: ProfileTab; label: string; icon: typeof UserRound }[] = [
    { id: "info", label: "Personal info", icon: UserRound },
    { id: "history", label: "Season history", icon: History },
    { id: "billing", label: "Plan & billing", icon: CreditCard },
  ];

  return (
    <main className="atlas-grid min-h-screen bg-background text-text-primary">
      {/* Header */}
      <div className="border-b border-jute-300/55 bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3.5">
          <Link
            href="/chat"
            className="flex items-center gap-1.5 text-sm font-semibold text-field-700 transition hover:-translate-x-1 hover:text-clay-500"
          >
            <ArrowLeft size={16} /> Back to chat
          </Link>
          <LeafMark size="sm" showWordmark={false} />
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-5 py-8 sm:py-12">
        {/* Identity strip */}
        <div className="mb-8 flex items-center gap-4 border-b border-jute-300/55 pb-8">
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-field-900 font-display text-xl font-semibold text-jute-300 shadow-card">
            {user.username
              .split(" ")
              .map((w) => w[0])
              .filter(Boolean)
              .slice(0, 2)
              .join("")
              .toUpperCase() || "·"}
          </span>
          <div>
            <p className="atlas-kicker">Personal field ledger</p>
            <h1 className="mt-1 font-display text-3xl tracking-[-0.04em]">{user.username}</h1>
            <p className="nums text-sm text-text-muted">{formatBdPhone(user.phone)}</p>
          </div>
          <span
            className={`ml-auto flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold ${
              tier === "free"
                ? "bg-surface-muted text-text-muted"
                : "bg-primary-100 text-primary-700"
            }`}
          >
            <BadgeCheck size={13} /> {TIERS.find((t) => t.id === tier)?.name}
          </span>
        </div>

        {/* Tabs */}
        <div className="mb-8 grid gap-2 border-b border-jute-300/55 pb-5 sm:grid-cols-3">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => selectTab(t.id)}
              aria-current={activeTab === t.id ? "page" : undefined}
              className={`flex min-h-11 items-center justify-center gap-2 border px-3 py-2 text-sm font-semibold transition duration-200 hover:-translate-y-0.5 ${
                activeTab === t.id
                  ? "border-field-700 bg-field-700 text-paper-50 shadow-card"
                  : "border-jute-300/60 bg-surface text-text-muted hover:border-field-400 hover:text-field-700 hover:shadow-card"
              }`}
            >
              <t.icon size={15} /> {t.label}
            </button>
          ))}
        </div>

        {/* --- Info --- */}
        {activeTab === "info" && (
          <div className="space-y-5">
            <section className="atlas-panel p-5 sm:p-7">
              <p className="atlas-kicker">Identity & location</p>
              <h2 className="mb-4 mt-2 font-display text-2xl">Account details</h2>
              <dl className="divide-y divide-border text-sm">
                {[
                  ["Name", user.username],
                  ["Mobile number", formatBdPhone(user.phone)],
                  ["Division", `${user.address.division_name} (${user.address.division_code})`],
                  ["District", `${user.address.district_name} (${user.address.district_code})`],
                  ["Upazila", `${user.address.upazila_name} (${user.address.upazila_code})`],
                  [
                    "Union",
                    user.address.union_name
                      ? `${user.address.union_name} (${user.address.union_code})`
                      : "",
                  ],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between py-2.5">
                    <dt className="text-text-muted">{k}</dt>
                    <dd className="font-medium text-text-primary">{v || "—"}</dd>
                  </div>
                ))}
              </dl>
            </section>

            <PasswordChange />

            <button
              type="button"
              onClick={() => logout()}
              className="flex w-full items-center justify-center gap-2 rounded-full border border-status-error/35 bg-surface px-4 py-2.5 text-sm font-semibold text-status-error transition hover:-translate-y-0.5 hover:bg-status-error-chip hover:shadow-card"
            >
              <LogOut size={16} /> Log out
            </button>
          </div>
        )}

        {/* --- History --- */}
        {activeTab === "history" && <HistoryTab />}

        {/* --- Billing --- */}
        {activeTab === "billing" && (
          <div className="space-y-4">
            <p className="text-sm text-text-muted">
              Your plan controls model quality and thinking depth. Subscription
              status is stored securely on the server.
            </p>
            <div className="grid gap-4 md:grid-cols-3">
              {TIERS.map((t) => {
                const current = t.id === tier;
                const canUpgrade = RANK[t.id] > RANK[tier];
                const included = RANK[t.id] < RANK[tier];
                const availableForCheckout =
                  t.id === "free" ||
                  subscribablePlanIds.includes(t.id as "plus" | "pro");
                const switchRequiresCancellation =
                  tier !== "free" && canUpgrade && availableForCheckout;
                return (
                  <div
                    key={t.id}
                    className={`flex flex-col border p-5 shadow-card transition duration-300 hover:-translate-y-1 hover:shadow-lift ${
                      current ? "border-field-500 ring-1 ring-field-200" : "border-jute-300/60"
                    } bg-surface`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-display text-lg font-semibold">{t.name}</span>
                      {t.id === "pro" && <Sprout size={16} className="text-primary-600" />}
                    </div>
                    <p className="text-xs text-text-muted">{t.tagline}</p>
                    <p className="nums mt-3 font-display text-2xl font-semibold">{t.price}</p>
                    <ul className="mt-4 flex-1 space-y-2 text-sm">
                      {t.features.map((f) => (
                        <li key={f} className="flex items-start gap-2 text-text-primary">
                          <Check size={15} className="mt-0.5 shrink-0 text-primary-600" /> {f}
                        </li>
                      ))}
                    </ul>
                    <div className="mt-5">
                      {current ? (
                        <span className="block rounded-xl bg-primary-100 py-2.5 text-center text-sm font-medium text-primary-700">
                          Current plan
                        </span>
                      ) : switchRequiresCancellation ? (
                        <span className="block rounded-xl border border-border px-3 py-2.5 text-center text-xs text-text-muted">
                          Cancel {TIERS.find((plan) => plan.id === tier)?.name}{" "}
                          before switching
                        </span>
                      ) : canUpgrade && availableForCheckout ? (
                        <button
                          type="button"
                          onClick={() =>
                            setCheckout({
                              id: t.id as PaidTierId,
                              name: t.name,
                              amount: serverPrices[t.id] ?? PRICE[t.id],
                            })
                          }
                          className="atlas-button w-full"
                        >
                          Upgrade to {t.name}
                        </button>
                      ) : canUpgrade ? (
                        <span className="block rounded-xl border border-border px-3 py-2.5 text-center text-xs text-text-muted">
                          Not provisioned for this BDApps application
                        </span>
                      ) : included ? (
                        <span className="block rounded-xl border border-border py-2.5 text-center text-sm text-text-muted">
                          Included
                        </span>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
            {tier === "pro" && (
              <p className="rounded-xl border border-primary-200 bg-primary-50 px-4 py-3 text-sm text-primary-800">
                You&apos;re on Pro — the top plan. Nothing more to upgrade.
              </p>
            )}
            {subscription?.status === "active" && tier !== "free" && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-sm">
                <div>
                  <p className="font-medium text-text-primary">
                    {subscription.provider === "bdapps"
                      ? "Verified by bdapps"
                      : "Demo subscription"}
                  </p>
                  <p className="text-xs text-text-muted">
                    {subscription.provider_status} · ৳{subscription.amount_bdt}/
                    {subscription.billing_cycle}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={cancelCurrentSubscription}
                  disabled={billingBusy}
                  className="rounded-lg border border-status-error/30 px-3 py-1.5 text-xs font-medium text-status-error transition hover:bg-status-error-chip disabled:opacity-60"
                >
                  {billingBusy ? "Cancelling…" : "Cancel subscription"}
                </button>
              </div>
            )}
            {billingMsg && (
              <p className="text-xs text-text-muted">{billingMsg}</p>
            )}
          </div>
        )}
      </div>

      {checkout && (
        <BdAppsCheckout
          planId={checkout.id}
          tierName={checkout.name}
          amount={checkout.amount}
          mobile={user.phone}
          provider={billingProvider}
          onClose={() => setCheckout(null)}
          onSuccess={(activeSubscription) => {
            setSubscription(activeSubscription);
            setTier(activeSubscription.plan_id);
            setBillingMsg(
              `${checkout.name} activated successfully through ${
                activeSubscription.provider === "bdapps" ? "BDApps" : "the development provider"
              }.`,
            );
            setCheckout(null);
          }}
        />
      )}
    </main>
  );
}

// --------------------------------------------------------------------------- //
function nowMinusMonths(months: number) {
  const date = new Date();
  date.setDate(1);
  date.setMonth(date.getMonth() - months);
  return date.getTime();
}

function HistoryTab() {
  const { data: sessions, isError } = useSessions();
  const { selectSession } = useChat();
  const router = useRouter();
  const list = sessions ?? [];
  const illustrative: Session[] = [
    {
      id: -1,
      title: "Boro crop comparison",
      message_count: 12,
      created_at: new Date(nowMinusMonths(5)).toISOString(),
      updated_at: new Date(nowMinusMonths(4)).toISOString(),
    },
    {
      id: -2,
      title: "Aman seasonal calendar",
      message_count: 9,
      created_at: new Date(nowMinusMonths(3)).toISOString(),
      updated_at: new Date(nowMinusMonths(2)).toISOString(),
    },
    {
      id: -3,
      title: "Tomato leaf check",
      message_count: 4,
      created_at: new Date(nowMinusMonths(1)).toISOString(),
      updated_at: new Date(nowMinusMonths(1)).toISOString(),
    },
  ];
  const usingFallback = list.length === 0;
  const summaryList = usingFallback ? illustrative : list;

  const continueChat = (id: number) => {
    selectSession(id);
    router.push("/chat");
  };

  const totalMessages = summaryList.reduce((sum, session) => sum + session.message_count, 0);
  const averageDepth = summaryList.length ? totalMessages / summaryList.length : 0;
  const now = Date.now();
  const activeRecently = summaryList.filter(
    (session) => now - new Date(session.updated_at).getTime() <= 30 * 24 * 60 * 60 * 1000,
  ).length;
  const deepest = [...summaryList].sort((a, b) => b.message_count - a.message_count).slice(0, 6);
  const maxDepth = Math.max(...deepest.map((session) => session.message_count), 1);
  const depthGroups = [
    {
      label: "Quick checks",
      description: "1–4 messages",
      value: summaryList.filter((session) => session.message_count <= 4).length,
      color: "bg-river-500",
    },
    {
      label: "Working sessions",
      description: "5–10 messages",
      value: summaryList.filter(
        (session) => session.message_count >= 5 && session.message_count <= 10,
      ).length,
      color: "bg-field-500",
    },
    {
      label: "Deep planning",
      description: "11+ messages",
      value: summaryList.filter((session) => session.message_count >= 11).length,
      color: "bg-clay-500",
    },
  ];
  const maxGroup = Math.max(...depthGroups.map((group) => group.value), 1);
  const months = Array.from({ length: 6 }, (_, index) => {
    const date = new Date();
    date.setDate(1);
    date.setMonth(date.getMonth() - (5 - index));
    const key = `${date.getFullYear()}-${date.getMonth()}`;
    return {
      key,
      label: date.toLocaleDateString("en-BD", { month: "short" }),
      value: summaryList.filter((session) => {
        const updated = new Date(session.updated_at);
        return `${updated.getFullYear()}-${updated.getMonth()}` === key;
      }).length,
    };
  });
  const maxMonth = Math.max(...months.map((month) => month.value), 1);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Chats" value={String(summaryList.length)} />
        <Stat label="Messages" value={String(totalMessages)} />
        <Stat label="Avg. depth" value={averageDepth.toFixed(1)} />
        <Stat label="Active · 30d" value={String(activeRecently)} />
      </div>

      {usingFallback && (
        <p className="border border-clay-200 bg-clay-50 px-4 py-3 text-xs leading-5 text-clay-700">
          {isError
            ? "The sessions endpoint could not be reached, so the charts below use an illustrative season sample."
            : "No saved sessions are available yet, so the charts below show an illustrative season sample."}{" "}
          Your real backend activity replaces this sample automatically.
        </p>
      )}

      <section className="atlas-panel p-5 sm:p-7">
        <p className="atlas-kicker">Conversation ledger</p>
        <h3 className="mb-4 mt-2 font-display text-2xl">Your chats</h3>
        {list.length === 0 ? (
          <p className="text-sm text-text-muted">No chats yet — start one from the chat page.</p>
        ) : (
          <div className="space-y-2">
            {list.map((s) => (
              <div
                key={s.id}
                className="flex flex-wrap items-center justify-between gap-2 border border-jute-300/55 px-3 py-3 text-sm transition duration-200 hover:-translate-y-0.5 hover:border-field-400 hover:bg-field-50 hover:shadow-card"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <MessageSquare size={15} className="shrink-0 text-primary-600" />
                  <div className="min-w-0">
                    <span className="block truncate font-medium text-text-primary">
                      {s.title || "New chat"}
                    </span>
                    <span className="text-xs text-text-muted">
                      {s.message_count} messages · updated{" "}
                      {new Date(s.updated_at).toLocaleDateString("en-BD", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => continueChat(s.id)}
                  className="flex items-center gap-1 rounded-full bg-field-700 px-3 py-1.5 text-xs font-semibold text-paper-50 transition hover:-translate-y-0.5 hover:bg-field-900"
                >
                  Continue chat <ArrowRight size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
        <section className="atlas-panel p-5 sm:p-7">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="atlas-kicker">Backend activity</p>
              <h3 className="mt-2 font-display text-2xl">Six-month rhythm</h3>
            </div>
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-500">
              sessions updated
            </span>
          </div>
          <div className="mt-7 flex h-48 items-end gap-3 border-b border-l border-jute-300/55 px-3 pt-4">
            {months.map((month) => (
              <div key={month.key} className="group flex h-full flex-1 flex-col justify-end">
                <span className="mb-2 text-center font-mono text-[10px] text-ink-500">
                  {month.value}
                </span>
                <div
                  className="min-h-1 bg-field-500 transition duration-300 group-hover:-translate-y-1 group-hover:bg-clay-500 group-hover:shadow-card"
                  style={{ height: `${Math.max((month.value / maxMonth) * 100, 4)}%` }}
                  title={`${month.value} sessions updated in ${month.label}`}
                />
                <span className="py-2 text-center font-mono text-[10px] uppercase text-ink-500">
                  {month.label}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section className="atlas-panel p-5 sm:p-7">
          <p className="atlas-kicker">Conversation shape</p>
          <h3 className="mt-2 font-display text-2xl">How deeply you plan</h3>
          <div className="mt-7 space-y-5">
            {depthGroups.map((group) => (
              <div key={group.label}>
                <div className="mb-2 flex items-end justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-ink-900">{group.label}</span>
                    <span className="text-xs text-ink-500">{group.description}</span>
                  </span>
                  <span className="font-mono text-sm text-ink-700">{group.value}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-paper-200/70">
                  <div
                    className={`h-full rounded-full ${group.color} transition-all duration-700`}
                    style={{ width: `${(group.value / maxGroup) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="atlas-panel p-5 sm:p-7">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="atlas-kicker">Message volume</p>
            <h3 className="mt-2 font-display text-2xl">Most detailed conversations</h3>
          </div>
          <span className="text-xs text-ink-500">
            {usingFallback ? "Illustrative fallback" : "From /api/chat/sessions"}
          </span>
        </div>
        {deepest.length === 0 ? (
          <p className="mt-6 text-sm text-ink-500">Message volume will appear after your first chat.</p>
        ) : (
          <ol className="mt-6 space-y-3">
            {deepest.map((session, index) => (
              <li key={session.id} className="grid items-center gap-3 sm:grid-cols-[28px_1fr_3fr_72px]">
                <span className="font-mono text-xs text-clay-500">0{index + 1}</span>
                <span className="truncate text-sm font-semibold text-ink-900">
                  {session.title || "New chat"}
                </span>
                <span className="h-2 overflow-hidden rounded-full bg-paper-200/70">
                  <span
                    className="block h-full rounded-full bg-gradient-to-r from-river-500 to-field-500 transition duration-500 hover:brightness-110"
                    style={{ width: `${(session.message_count / maxDepth) * 100}%` }}
                  />
                </span>
                <span className="text-right font-mono text-xs text-ink-500">
                  {session.message_count} msg
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

// --------------------------------------------------------------------------- //
function PasswordChange() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSuccess(false);
    if (next.length < 8)
      return setMsg("New password must be at least 8 characters.");
    if (next !== confirm) return setMsg("Passwords do not match.");
    setBusy(true);
    setMsg(null);
    try {
      const result = await apiChangePassword(cur, next);
      setMsg(result.message);
      setSuccess(true);
      setCur("");
      setNext("");
      setConfirm("");
    } catch (error) {
      setMsg(error instanceof Error ? error.message : "Could not update password.");
    } finally {
      setBusy(false);
    }
  };

  const input =
    "min-h-11 w-full rounded-lg border border-jute-300/70 bg-paper-50 px-3.5 py-2.5 text-sm outline-none transition focus:border-clay-400 focus:ring-0 focus:shadow-[0_8px_24px_-18px_rgba(23,38,28,0.55)]";

  return (
    <section className="atlas-panel p-5 sm:p-7">
      <p className="atlas-kicker">Account security</p>
      <h2 className="mb-4 mt-2 font-display text-2xl">Update password</h2>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <input
          type="password"
          placeholder="Current password"
          value={cur}
          onChange={(e) => setCur(e.target.value)}
          className={input}
          autoComplete="current-password"
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <input
            type="password"
            placeholder="New password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className={input}
            autoComplete="new-password"
          />
          <input
            type="password"
            placeholder="Confirm new password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={input}
            autoComplete="new-password"
          />
        </div>
        {msg && (
          <p
            className={`text-xs ${
              success ? "text-primary-700" : "text-status-error"
            }`}
          >
            {msg}
          </p>
        )}
        <button
          type="submit"
          disabled={busy || !cur || !next || !confirm}
          className="atlas-button self-start disabled:opacity-60"
        >
          {busy ? "Updating…" : "Update password"}
        </button>
      </form>
    </section>
  );
}
