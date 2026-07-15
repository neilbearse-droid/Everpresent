import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      {/* Land on the dashboard after a successful sign-in (otherwise Clerk
          returns to "/", which shows Sign in again — an apparent loop). */}
      <SignIn forceRedirectUrl="/dashboard" />
    </main>
  );
}
