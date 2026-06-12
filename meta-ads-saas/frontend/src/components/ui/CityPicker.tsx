"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { X, MapPin, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

export type GeoCity = {
  key: string;
  name: string;
  region?: string;
  country_code?: string;
  country_name?: string;
};

/**
 * Autocomplete city picker backed by Meta's geo-location search API.
 * Only shows cities that exist in Meta's database for the given country.
 */
export function CityPicker({
  value,
  onChange,
  countryCode = "",
  placeholder = "Search cities...",
  compact = false,
}: {
  value: GeoCity[];
  onChange: (cities: GeoCity[]) => void;
  countryCode?: string;
  placeholder?: string;
  compact?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<GeoCity[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Debounced search
  const search = useCallback(
    (q: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (q.length < 2) {
        setSuggestions([]);
        return;
      }
      debounceRef.current = setTimeout(async () => {
        setLoading(true);
        try {
          const { data } = await api.searchGeoCities(q, countryCode);
          // Filter out already-selected cities
          const selectedKeys = new Set(value.map((c) => c.key));
          setSuggestions((data.cities || []).filter((c) => !selectedKeys.has(c.key)));
          setOpen(true);
        } catch {
          setSuggestions([]);
        } finally {
          setLoading(false);
        }
      }, 300);
    },
    [countryCode, value],
  );

  useEffect(() => {
    search(query);
  }, [query, search]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const addCity = (city: GeoCity) => {
    if (value.some((c) => c.key === city.key)) return;
    onChange([...value, city]);
    setQuery("");
    setSuggestions([]);
    setOpen(false);
  };

  const removeCity = (key: string) => {
    onChange(value.filter((c) => c.key !== key));
  };

  const textSize = compact ? "text-xs" : "text-sm";

  return (
    <div className="space-y-1.5" ref={wrapperRef}>
      {/* Selected tags */}
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((city) => (
            <span
              key={city.key}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-[11px]"
            >
              <MapPin className="w-2.5 h-2.5" />
              {city.name}
              {city.region && <span className="text-emerald-500/50">{city.region}</span>}
              <button
                type="button"
                onClick={() => removeCity(city.key)}
                className="hover:text-white transition-colors"
              >
                <X className="w-2.5 h-2.5" />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Search input */}
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => suggestions.length > 0 && setOpen(true)}
          placeholder={value.length === 0 ? placeholder : "Add another city..."}
          className={`w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white ${textSize} placeholder-gray-600 focus:outline-none focus:border-emerald-500/40 transition-all pr-8`}
        />
        {loading && (
          <Loader2 className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 animate-spin" />
        )}

        {/* Dropdown */}
        {open && suggestions.length > 0 && (
          <div className="absolute z-50 mt-1 w-full max-h-[200px] overflow-y-auto rounded-xl border border-white/[0.08] bg-[#1a1a2e] shadow-xl">
            {suggestions.map((city) => (
              <button
                key={city.key}
                type="button"
                onClick={() => addCity(city)}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-white/[0.06] transition-colors"
              >
                <MapPin className="w-3 h-3 text-emerald-400 shrink-0" />
                <div className="min-w-0">
                  <span className={`${textSize} text-white`}>{city.name}</span>
                  {city.region && (
                    <span className={`${textSize} text-gray-500 ml-1.5`}>{city.region}</span>
                  )}
                  {city.country_name && (
                    <span className="text-[10px] text-gray-600 ml-1.5">{city.country_name}</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <p className="text-[10px] text-gray-600">
        Leave empty to target entire country. Type to search Meta&apos;s city database.
      </p>
    </div>
  );
}
