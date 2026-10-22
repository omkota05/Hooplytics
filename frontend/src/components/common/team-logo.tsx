import Image from "next/image";

import { cn } from "@/lib/utils";
import type { Team } from "@/lib/types";

export function TeamLogo({
  team,
  size = 28,
  className,
}: {
  team: Pick<Team, "abbreviation" | "logo_url" | "display_name">;
  size?: number;
  className?: string;
}) {
  if (!team.logo_url) {
    return (
      <span
        className={cn(
          "inline-flex items-center justify-center rounded-full bg-secondary text-[10px] font-bold",
          className,
        )}
        style={{ width: size, height: size }}
      >
        {team.abbreviation}
      </span>
    );
  }
  return (
    <Image
      src={team.logo_url}
      alt={team.display_name}
      width={size}
      height={size}
      className={cn("shrink-0 object-contain", className)}
    />
  );
}
