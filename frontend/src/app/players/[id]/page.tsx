import { notFound } from "next/navigation";

import { PlayerProfileView } from "./player-profile-view";

export default async function PlayerPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ stat?: string; opponent?: string }>;
}) {
  const { id } = await params;
  const { stat, opponent } = await searchParams;
  const playerId = Number(id);
  if (!Number.isInteger(playerId) || playerId <= 0) notFound();
  const opponentId = opponent && Number.isInteger(Number(opponent)) ? Number(opponent) : null;
  return <PlayerProfileView playerId={playerId} initialStat={stat} initialOpponentId={opponentId} />;
}
