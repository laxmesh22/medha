/** Exercises the clinic station coach can run and score.
 * Keep this list in step with EXERCISES in hub/physiobuddy_hub/core/coach.py.
 * Inward rotation and pendulum stay in the library so a clinician can still prescribe them.
 */
export const STATION_MEASURED = ["flexion", "abduction", "external_rotation"] as const;

const MEASURED = new Set<string>(STATION_MEASURED);

export function stationMeasured(exerciseId: string): boolean {
  return MEASURED.has(exerciseId);
}

export function stationMeasureLabel(exerciseId: string): string {
  return stationMeasured(exerciseId) ? "Measured at the station" : "Home exercise: not measured yet";
}
