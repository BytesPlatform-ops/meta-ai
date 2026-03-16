"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";

/* ── Types ──────────────────────────────────────────────────────── */

export type DateRangeValue =
  | { preset: string; since?: undefined; until?: undefined }
  | { preset?: undefined; since: string; until: string };

interface Props {
  datePreset: string;
  since?: string;
  until?: string;
  onChange: (value: DateRangeValue) => void;
}

const PRESETS = [
  { label: "Today", value: "today" },
  { label: "Last 7 days", value: "last_7d" },
  { label: "Last 14 days", value: "last_14d" },
  { label: "Last 30 days", value: "last_30d" },
  { label: "Lifetime", value: "maximum" },
];

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const SHORT_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/* ── Helpers ────────────────────────────────────────────────────── */

function toYMD(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseYMD(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function formatDisplay(d: Date): string {
  return `${d.getDate()} ${SHORT_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

function firstDayOfMonth(year: number, month: number): number {
  return new Date(year, month, 1).getDay(); // 0=Sun
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function isBetween(d: Date, start: Date, end: Date): boolean {
  const t = d.getTime();
  return t > start.getTime() && t < end.getTime();
}

function presetLabel(preset: string): string {
  return PRESETS.find((p) => p.value === preset)?.label || preset;
}

function getDisplayLabel(preset: string, since?: string, until?: string): string {
  if (since && until) {
    return `${formatDisplay(parseYMD(since))} – ${formatDisplay(parseYMD(until))}`;
  }
  return presetLabel(preset);
}

/* ── Calendar Grid ──────────────────────────────────────────────── */

function CalendarMonth({
  year,
  month,
  rangeStart,
  rangeEnd,
  hoverDate,
  onDateClick,
  onDateHover,
}: {
  year: number;
  month: number;
  rangeStart: Date | null;
  rangeEnd: Date | null;
  hoverDate: Date | null;
  onDateClick: (d: Date) => void;
  onDateHover: (d: Date | null) => void;
}) {
  const today = new Date();
  const totalDays = daysInMonth(year, month);
  const startDay = firstDayOfMonth(year, month);
  const cells: (number | null)[] = [];
  for (let i = 0; i < startDay; i++) cells.push(null);
  for (let d = 1; d <= totalDays; d++) cells.push(d);

  // Determine effective end for highlighting
  const effectiveEnd = rangeEnd || (rangeStart && hoverDate && hoverDate > rangeStart ? hoverDate : null);

  return (
    <div className="w-[230px] shrink-0">
      <div className="text-center text-sm font-semibold text-white mb-3">
        {MONTHS[month]} {year}
      </div>
      <div className="grid grid-cols-7 gap-0.5 mb-1">
        {DAYS.map((d) => (
          <div key={d} className="text-center text-[10px] text-gray-500 font-medium py-1">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((day, i) => {
          if (day === null) return <div key={`e-${i}`} className="h-8" />;
          const d = new Date(year, month, day);
          const isToday = isSameDay(d, today);
          const isStart = rangeStart && isSameDay(d, rangeStart);
          const isEnd = effectiveEnd && isSameDay(d, effectiveEnd);
          const inRange = rangeStart && effectiveEnd && isBetween(d, rangeStart, effectiveEnd);
          const isFuture = d > today;

          let cls = "h-8 w-full rounded-md text-xs flex items-center justify-center transition-all cursor-pointer ";
          if (isStart || isEnd) {
            cls += "bg-blue-500 text-white font-semibold ";
          } else if (inRange) {
            cls += "bg-blue-500/20 text-blue-300 ";
          } else if (isToday) {
            cls += "ring-1 ring-blue-400/50 text-blue-400 font-medium hover:bg-white/[0.08] ";
          } else if (isFuture) {
            cls += "text-gray-600 cursor-not-allowed ";
          } else {
            cls += "text-gray-300 hover:bg-white/[0.08] ";
          }

          return (
            <button
              key={day}
              className={cls}
              disabled={isFuture}
              onClick={() => onDateClick(d)}
              onMouseEnter={() => onDateHover(d)}
              onMouseLeave={() => onDateHover(null)}
            >
              {day}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── Main Component ─────────────────────────────────────────────── */

export default function DateRangePicker({ datePreset, since, until, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Calendar navigation
  const now = new Date();
  const [leftMonth, setLeftMonth] = useState(now.getMonth() === 0 ? 11 : now.getMonth() - 1);
  const [leftYear, setLeftYear] = useState(now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear());

  // Selection state (draft, committed on "Update")
  const [rangeStart, setRangeStart] = useState<Date | null>(since ? parseYMD(since) : null);
  const [rangeEnd, setRangeEnd] = useState<Date | null>(until ? parseYMD(until) : null);
  const [hoverDate, setHoverDate] = useState<Date | null>(null);
  const [pickingEnd, setPickingEnd] = useState(false);
  const [draftPreset, setDraftPreset] = useState<string | null>(since && until ? null : datePreset);

  // Right month is always left + 1
  const rightMonth = (leftMonth + 1) % 12;
  const rightYear = leftMonth === 11 ? leftYear + 1 : leftYear;

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Sync external props to internal state when they change
  useEffect(() => {
    if (since && until) {
      setRangeStart(parseYMD(since));
      setRangeEnd(parseYMD(until));
      setDraftPreset(null);
    } else {
      setDraftPreset(datePreset);
      setRangeStart(null);
      setRangeEnd(null);
    }
  }, [datePreset, since, until]);

  const navPrev = () => {
    if (leftMonth === 0) { setLeftMonth(11); setLeftYear(leftYear - 1); }
    else setLeftMonth(leftMonth - 1);
  };
  const navNext = () => {
    // Don't go past current month
    if (rightYear > now.getFullYear() || (rightYear === now.getFullYear() && rightMonth >= now.getMonth())) return;
    if (leftMonth === 11) { setLeftMonth(0); setLeftYear(leftYear + 1); }
    else setLeftMonth(leftMonth + 1);
  };

  const handleDateClick = useCallback((d: Date) => {
    setDraftPreset(null);
    if (!pickingEnd || !rangeStart) {
      setRangeStart(d);
      setRangeEnd(null);
      setPickingEnd(true);
    } else {
      if (d < rangeStart) {
        setRangeStart(d);
        setRangeEnd(rangeStart);
      } else {
        setRangeEnd(d);
      }
      setPickingEnd(false);
    }
  }, [pickingEnd, rangeStart]);

  const handlePresetClick = (preset: string) => {
    setDraftPreset(preset);
    setRangeStart(null);
    setRangeEnd(null);
    setPickingEnd(false);
  };

  const handleUpdate = () => {
    if (draftPreset) {
      onChange({ preset: draftPreset });
    } else if (rangeStart && rangeEnd) {
      onChange({ since: toYMD(rangeStart), until: toYMD(rangeEnd) });
    }
    setOpen(false);
  };

  const handleCancel = () => {
    // Reset to current values
    if (since && until) {
      setRangeStart(parseYMD(since));
      setRangeEnd(parseYMD(until));
      setDraftPreset(null);
    } else {
      setDraftPreset(datePreset);
      setRangeStart(null);
      setRangeEnd(null);
    }
    setPickingEnd(false);
    setOpen(false);
  };

  const canUpdate = draftPreset || (rangeStart && rangeEnd);

  return (
    <div className="relative" ref={ref}>
      {/* Trigger button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/[0.04] border border-white/[0.06] hover:bg-white/[0.08] transition-all text-sm text-gray-300"
      >
        <Calendar className="w-4 h-4 text-gray-500" />
        <span className="font-medium">{getDisplayLabel(datePreset, since, until)}</span>
        <ChevronRight className={`w-3.5 h-3.5 text-gray-500 transition-transform ${open ? "rotate-90" : ""}`} />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 bg-[#1a1a2e] border border-white/[0.08] rounded-2xl shadow-2xl p-4 animate-fade-in w-[700px] max-w-[calc(100vw-2rem)]"
        >
          <div className="flex gap-5">
            {/* Presets sidebar */}
            <div className="w-[130px] flex flex-col gap-1 border-r border-white/[0.06] pr-4">
              {PRESETS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => handlePresetClick(p.value)}
                  className={`text-left px-3 py-2 rounded-lg text-sm transition-all ${
                    draftPreset === p.value
                      ? "bg-blue-500/20 text-blue-400 font-medium"
                      : "text-gray-400 hover:bg-white/[0.06] hover:text-gray-200"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* Calendars */}
            <div className="flex-1">
              {/* Nav arrows + month labels */}
              <div className="flex items-center justify-between mb-3">
                <button onClick={navPrev} className="w-7 h-7 rounded-lg hover:bg-white/[0.08] flex items-center justify-center text-gray-400">
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <div className="flex-1" />
                <button onClick={navNext} className="w-7 h-7 rounded-lg hover:bg-white/[0.08] flex items-center justify-center text-gray-400">
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>

              <div className="flex gap-6">
                <CalendarMonth
                  year={leftYear}
                  month={leftMonth}
                  rangeStart={rangeStart}
                  rangeEnd={rangeEnd}
                  hoverDate={hoverDate}
                  onDateClick={handleDateClick}
                  onDateHover={setHoverDate}
                />
                <CalendarMonth
                  year={rightYear}
                  month={rightMonth}
                  rangeStart={rangeStart}
                  rangeEnd={rangeEnd}
                  hoverDate={hoverDate}
                  onDateClick={handleDateClick}
                  onDateHover={setHoverDate}
                />
              </div>

              {/* Date inputs */}
              <div className="flex items-center gap-2 mt-4 pt-3 border-t border-white/[0.06]">
                <input
                  type="text"
                  readOnly
                  value={rangeStart ? formatDisplay(rangeStart) : "Start date"}
                  className="flex-1 px-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-gray-300 text-center"
                />
                <span className="text-gray-500 text-sm">–</span>
                <input
                  type="text"
                  readOnly
                  value={rangeEnd ? formatDisplay(rangeEnd) : "End date"}
                  className="flex-1 px-3 py-1.5 rounded-lg bg-white/[0.04] border border-white/[0.08] text-sm text-gray-300 text-center"
                />
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-white/[0.06]">
            <button
              onClick={handleCancel}
              className="px-4 py-2 rounded-lg text-sm text-gray-400 hover:bg-white/[0.06] transition-all"
            >
              Cancel
            </button>
            <button
              onClick={handleUpdate}
              disabled={!canUpdate}
              className="px-5 py-2 rounded-lg text-sm font-medium bg-blue-500 text-white hover:bg-blue-600 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Update
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
