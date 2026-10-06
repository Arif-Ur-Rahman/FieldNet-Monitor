"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/gateways", label: "Fleet" },
  { href: "/sensors", label: "Sensors" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <header className="border-b border-slate-200 bg-white">
      <nav className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
        <span className="font-semibold text-slate-900">FieldNet Monitor</span>
        {LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className={
              pathname === link.href
                ? "text-sm font-medium text-slate-900 underline underline-offset-4"
                : "text-sm text-slate-500 hover:text-slate-900"
            }
          >
            {link.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
