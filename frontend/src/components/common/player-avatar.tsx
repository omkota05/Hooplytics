"use client";

import Image from "next/image";
import { useState } from "react";

import { cn } from "@/lib/utils";

export function PlayerAvatar({
  name,
  src,
  size = 40,
  className,
}: {
  name: string;
  src: string | null;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const initials = name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("");

  return (
    <div
      className={cn(
        "relative shrink-0 overflow-hidden rounded-full bg-gradient-to-br from-secondary to-accent ring-1 ring-border",
        className,
      )}
      style={{ width: size, height: size }}
    >
      {src && !failed ? (
        <Image
          src={src}
          alt={name}
          fill
          sizes={`${size}px`}
          className="object-cover object-top"
          onError={() => setFailed(true)}
        />
      ) : (
        <span
          className="flex h-full w-full items-center justify-center font-semibold text-muted-foreground"
          style={{ fontSize: size * 0.36 }}
        >
          {initials}
        </span>
      )}
    </div>
  );
}
