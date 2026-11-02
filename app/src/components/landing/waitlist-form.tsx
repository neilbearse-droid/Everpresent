"use client";

import { useActionState, useEffect, useId, useState } from "react";
import { joinWaitlist, type WaitlistState } from "@/app/waitlist-actions";

const INDUSTRIES = [
  "Higher education",
  "Financial services",
  "Insurance",
  "Healthcare",
  "SaaS / software",
  "Professional services",
  "Retail / ecommerce",
  "Travel / hospitality",
  "Real estate",
  "Manufacturing / industrial",
  "Nonprofit / association",
  "Agency / consultancy",
  "Media / publishing",
  "Other",
];

const inputClass =
  "field w-full px-3 py-2.5 text-[14px] placeholder:text-[var(--text-3)]";

export function WaitlistForm({ source = "landing" }: { source?: string }) {
  const [state, action, pending] = useActionState<WaitlistState, FormData>(joinWaitlist, null);
  const [industry, setIndustry] = useState("");
  // The form appears twice on the page, so every id is namespaced: duplicate
  // ids would break the second copy's labels.
  const uid = useId();
  const [utm, setUtm] = useState("{}");

  // Campaign tags, read on the client so the page itself can stay cached.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const keys = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref"];
    const found: Record<string, string> = {};
    for (const key of keys) {
      const value = params.get(key);
      if (value) found[key] = value;
    }
    setUtm(JSON.stringify(found));
  }, []);

  if (state?.ok) {
    return (
      <div className="card p-6 sm:p-7" aria-live="polite">
        <p className="ep-eyebrow">Request received</p>
        <h3 className="mt-2 text-[20px] font-semibold tracking-[-0.02em]">{state.message}</h3>
        <p className="mt-3 text-[14px] leading-relaxed text-[var(--text-2)]">
          We take on a few accounts at a time, so it might be a couple of weeks. When we come
          back we&apos;ll have questions about your category and some early numbers on it.
        </p>
        <p className="mt-4 text-[13px] text-[var(--text-3)]">
          Anything useful to add in the meantime, send it to{" "}
          <a className="bp-link" href="mailto:hello@everpresent.io">
            hello@everpresent.io
          </a>
          .
        </p>
      </div>
    );
  }

  return (
    <form action={action} className="card p-6 sm:p-7" noValidate={false}>
      <p className="ep-eyebrow">Request access</p>
      <h3 className="mt-2 text-[20px] font-semibold tracking-[-0.02em]">
        Start with your own numbers
      </h3>
      <p className="mt-2 text-[13.5px] leading-relaxed text-[var(--text-2)]">
        Five fields, which tell us what to measure. The first conversation is then about your
        category and the competitors you came here worried about.
      </p>

      <input type="hidden" name="source" value={source} />
      <input type="hidden" name="utm" value={utm} />
      {/* Honeypot: hidden from people, irresistible to bots. */}
      <div aria-hidden className="absolute h-0 w-0 overflow-hidden opacity-0">
        <label htmlFor={`${uid}-website`}>Website</label>
        <input id={`${uid}-website`} name="website" type="text" tabIndex={-1} autoComplete="off" />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3.5 sm:grid-cols-2">
        <div className="sm:col-span-1">
          <label htmlFor={`${uid}-name`} className="bp-label">
            Name
          </label>
          <input
            id={`${uid}-name`}
            name="name"
            required
            autoComplete="name"
            maxLength={120}
            placeholder="Dana Okoro"
            className={`mt-1.5 ${inputClass}`}
          />
        </div>
        <div className="sm:col-span-1">
          <label htmlFor={`${uid}-email`} className="bp-label">
            Work email
          </label>
          <input
            id={`${uid}-email`}
            name="email"
            type="email"
            required
            autoComplete="email"
            maxLength={254}
            placeholder="dana@company.com"
            className={`mt-1.5 ${inputClass}`}
          />
        </div>
        <div className="sm:col-span-1">
          <label htmlFor={`${uid}-title`} className="bp-label">
            Title
          </label>
          <input
            id={`${uid}-title`}
            name="title"
            autoComplete="organization-title"
            maxLength={120}
            placeholder="VP Marketing"
            className={`mt-1.5 ${inputClass}`}
          />
        </div>
        <div className="sm:col-span-1">
          <label htmlFor={`${uid}-company`} className="bp-label">
            Company
          </label>
          <input
            id={`${uid}-company`}
            name="company"
            autoComplete="organization"
            maxLength={160}
            placeholder="Northpeak"
            className={`mt-1.5 ${inputClass}`}
          />
        </div>
        <div className="sm:col-span-2">
          <label htmlFor={`${uid}-industry`} className="bp-label">
            Industry
          </label>
          <select
            id={`${uid}-industry`}
            name="industry"
            value={industry}
            onChange={(event) => setIndustry(event.target.value)}
            className={`mt-1.5 ${inputClass}`}
          >
            <option value="">Select an industry</option>
            {INDUSTRIES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
        {industry === "Other" && (
          <div className="sm:col-span-2">
            <label htmlFor={`${uid}-industry-other`} className="bp-label">
              Which industry?
            </label>
            <input
              id={`${uid}-industry-other`}
              name="industry_other"
              maxLength={80}
              placeholder="Tell us in a few words"
              className={`mt-1.5 ${inputClass}`}
            />
          </div>
        )}
      </div>

      <button
        type="submit"
        disabled={pending}
        className="btn ep-cta mt-5 w-full px-5 py-3 text-[14px]"
      >
        {pending ? "Sending…" : "Request access"}
      </button>

      {state && !state.ok && (
        <p className="mt-3 text-[13px] text-[var(--accent-2)]" role="alert">
          {state.message}
        </p>
      )}

      <p className="mt-4 text-[12px] leading-relaxed text-[var(--text-3)]">
        One email when your account is ready. We don&apos;t run a newsletter or sell lists, and
        we&apos;ll delete your details whenever you ask.
      </p>
    </form>
  );
}
