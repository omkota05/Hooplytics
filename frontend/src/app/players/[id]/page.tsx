import { notFound } from "next/navigation";

import { PlayerProfileView } from "./player-profile-view";

export default async function PlayerPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ stat?: string; opponent?: string; line?: string }>;
}) {
  const { id } = await params;
  const { stat, opponent, line } = await searchParams;
  const playerId = Number(id);
  if (!Number.isInteger(playerId) || playerId <= 0) notFound();
  const opponentId = opponent && Number.isInteger(Number(opponent)) ? Number(opponent) : null;
  const initialLine = line && Number.isFinite(Number(line)) ? Number(line) : undefined;
  return (
    <PlayerProfileView
      playerId={playerId}
      initialStat={stat}
      initialOpponentId={opponentId}
      initialLine={initialLine}
    />
  );
}
