export function computeMaxCount(
  chunkCounts: number[],
  questionsPerChunk: number,
  maxDatasetRows = 5000,
): number {
  const total =
    chunkCounts.reduce((sum, count) => sum + count, 0) * questionsPerChunk;
  return Math.min(total, maxDatasetRows);
}
