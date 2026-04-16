import { create } from "zustand";
import type { ForecastSession, AssumptionRow, ForecastPeriod } from "../api/forecasts";

interface ForecastStore {
  activeSession: ForecastSession | null;
  setActiveSession: (session: ForecastSession | null) => void;
  updateAssumption: (concept: string, updates: Partial<AssumptionRow>) => void;
  addForecastPeriod: (period: ForecastPeriod) => void;
  removeForecastPeriod: (label: string) => void;
  isDirty: boolean;
  setDirty: (dirty: boolean) => void;
  // Currently selected row for method panel
  selectedRowConcept: string | null;
  setSelectedRowConcept: (concept: string | null) => void;
}

export const useForecastStore = create<ForecastStore>((set, get) => ({
  activeSession: null,
  isDirty: false,
  selectedRowConcept: null,

  setActiveSession: (session) => set({ activeSession: session, isDirty: false }),

  updateAssumption: (concept, updates) => {
    const session = get().activeSession;
    if (!session) return;
    const assumptions = session.assumptions.map((a) =>
      a.concept === concept ? { ...a, ...updates } : a
    );
    set({
      activeSession: { ...session, assumptions },
      isDirty: true,
    });
  },

  addForecastPeriod: (period) => {
    const session = get().activeSession;
    if (!session) return;
    const already = session.forecast_periods.find((p) => p.label === period.label);
    if (already) return;
    set({
      activeSession: {
        ...session,
        forecast_periods: [...session.forecast_periods, period],
      },
      isDirty: true,
    });
  },

  removeForecastPeriod: (label) => {
    const session = get().activeSession;
    if (!session) return;
    set({
      activeSession: {
        ...session,
        forecast_periods: session.forecast_periods.filter((p) => p.label !== label),
      },
      isDirty: true,
    });
  },

  setDirty: (dirty) => set({ isDirty: dirty }),
  setSelectedRowConcept: (concept) => set({ selectedRowConcept: concept }),
}));
