import { notFound } from "next/navigation";

import { MatchupView } from "./matchup-view";

export default async function MatchupPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ player?: string }>;
}) {
  const { id } = await params;
  const { player } = await searchParams;
  const gameId = Number(id);
  if (!Number.isInteger(gameId) || gameId <= 0) notFound();
  return <MatchupView gameId={gameId} initialPlayerId={player ? Number(player) : null} />;
}
