import { ApiDownBanner } from "@/components/api-status";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <ApiDownBanner />
      {children}
    </>
  );
}
