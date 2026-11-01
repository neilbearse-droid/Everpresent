"use server";

const API_ORIGIN = process.env.API_ORIGIN ?? "http://localhost:8000";

export type WaitlistState = {
  ok: boolean;
  message: string;
  alreadyOnList?: boolean;
} | null;

/** The landing-page form posts here. Deliberately NOT `apiFetch`: this is the
 * public form, so no Clerk session is read and no token is forwarded. The
 * backend validates and stores the row. */
export async function joinWaitlist(
  _prev: WaitlistState,
  formData: FormData,
): Promise<WaitlistState> {
  const text = (key: string) => String(formData.get(key) ?? "").trim();
  const industry = text("industry") === "Other" ? text("industry_other") : text("industry");

  if (!text("name")) return { ok: false, message: "Please add your name." };
  if (!text("email").includes("@")) return { ok: false, message: "Please check the email address." };

  const body = {
    name: text("name"),
    email: text("email"),
    title: text("title"),
    company: text("company"),
    industry,
    source: text("source") || "landing",
    utm: JSON.parse(text("utm") || "{}") as Record<string, string>,
    website: text("website"), // honeypot
  };

  let res: Response;
  try {
    res = await fetch(`${API_ORIGIN}/api/waitlist`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return {
      ok: false,
      message: "We couldn't reach the server. Try again, or email hello@everpresent.io.",
    };
  }

  if (res.status === 429) {
    return { ok: false, message: "That's a lot of signups from one place. Try again later." };
  }
  if (!res.ok) {
    let detail = "";
    try {
      const parsed = (await res.json()) as { detail?: unknown };
      detail = typeof parsed.detail === "string" ? parsed.detail : "";
    } catch {
      detail = "";
    }
    return { ok: false, message: detail || "Something went wrong. Please try again." };
  }

  const parsed = (await res.json()) as { already_on_list?: boolean };
  return {
    ok: true,
    alreadyOnList: Boolean(parsed.already_on_list),
    message: parsed.already_on_list
      ? "You're already on the list. We've updated your details."
      : "You're on the list.",
  };
}
