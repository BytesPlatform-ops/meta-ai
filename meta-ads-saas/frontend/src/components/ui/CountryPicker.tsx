"use client";

import { useState } from "react";
import { X, Globe, Check } from "lucide-react";

const ALL_COUNTRIES = [
  { value: "AF", label: "Afghanistan" },
  { value: "AL", label: "Albania" },
  { value: "DZ", label: "Algeria" },
  { value: "AO", label: "Angola" },
  { value: "AR", label: "Argentina" },
  { value: "AM", label: "Armenia" },
  { value: "AU", label: "Australia" },
  { value: "AT", label: "Austria" },
  { value: "AZ", label: "Azerbaijan" },
  { value: "BH", label: "Bahrain" },
  { value: "BD", label: "Bangladesh" },
  { value: "BY", label: "Belarus" },
  { value: "BE", label: "Belgium" },
  { value: "BJ", label: "Benin" },
  { value: "BO", label: "Bolivia" },
  { value: "BA", label: "Bosnia & Herzegovina" },
  { value: "BW", label: "Botswana" },
  { value: "BR", label: "Brazil" },
  { value: "BN", label: "Brunei" },
  { value: "BG", label: "Bulgaria" },
  { value: "BF", label: "Burkina Faso" },
  { value: "KH", label: "Cambodia" },
  { value: "CM", label: "Cameroon" },
  { value: "CA", label: "Canada" },
  { value: "CL", label: "Chile" },
  { value: "CN", label: "China" },
  { value: "CO", label: "Colombia" },
  { value: "CD", label: "Congo (DRC)" },
  { value: "CR", label: "Costa Rica" },
  { value: "CI", label: "Côte d'Ivoire" },
  { value: "HR", label: "Croatia" },
  { value: "CY", label: "Cyprus" },
  { value: "CZ", label: "Czech Republic" },
  { value: "DK", label: "Denmark" },
  { value: "DO", label: "Dominican Republic" },
  { value: "EC", label: "Ecuador" },
  { value: "EG", label: "Egypt" },
  { value: "SV", label: "El Salvador" },
  { value: "EE", label: "Estonia" },
  { value: "ET", label: "Ethiopia" },
  { value: "FI", label: "Finland" },
  { value: "FR", label: "France" },
  { value: "GA", label: "Gabon" },
  { value: "GE", label: "Georgia" },
  { value: "DE", label: "Germany" },
  { value: "GH", label: "Ghana" },
  { value: "GR", label: "Greece" },
  { value: "GT", label: "Guatemala" },
  { value: "GN", label: "Guinea" },
  { value: "HN", label: "Honduras" },
  { value: "HK", label: "Hong Kong" },
  { value: "HU", label: "Hungary" },
  { value: "IS", label: "Iceland" },
  { value: "IN", label: "India" },
  { value: "ID", label: "Indonesia" },
  { value: "IQ", label: "Iraq" },
  { value: "IE", label: "Ireland" },
  { value: "IL", label: "Israel" },
  { value: "IT", label: "Italy" },
  { value: "JM", label: "Jamaica" },
  { value: "JP", label: "Japan" },
  { value: "JO", label: "Jordan" },
  { value: "KZ", label: "Kazakhstan" },
  { value: "KE", label: "Kenya" },
  { value: "KW", label: "Kuwait" },
  { value: "KG", label: "Kyrgyzstan" },
  { value: "LA", label: "Laos" },
  { value: "LV", label: "Latvia" },
  { value: "LB", label: "Lebanon" },
  { value: "LY", label: "Libya" },
  { value: "LT", label: "Lithuania" },
  { value: "LU", label: "Luxembourg" },
  { value: "MG", label: "Madagascar" },
  { value: "MW", label: "Malawi" },
  { value: "MY", label: "Malaysia" },
  { value: "MV", label: "Maldives" },
  { value: "ML", label: "Mali" },
  { value: "MT", label: "Malta" },
  { value: "MU", label: "Mauritius" },
  { value: "MX", label: "Mexico" },
  { value: "MD", label: "Moldova" },
  { value: "MN", label: "Mongolia" },
  { value: "ME", label: "Montenegro" },
  { value: "MA", label: "Morocco" },
  { value: "MZ", label: "Mozambique" },
  { value: "MM", label: "Myanmar" },
  { value: "NA", label: "Namibia" },
  { value: "NP", label: "Nepal" },
  { value: "NL", label: "Netherlands" },
  { value: "NZ", label: "New Zealand" },
  { value: "NI", label: "Nicaragua" },
  { value: "NE", label: "Niger" },
  { value: "NG", label: "Nigeria" },
  { value: "MK", label: "North Macedonia" },
  { value: "NO", label: "Norway" },
  { value: "OM", label: "Oman" },
  { value: "PK", label: "Pakistan" },
  { value: "PS", label: "Palestine" },
  { value: "PA", label: "Panama" },
  { value: "PY", label: "Paraguay" },
  { value: "PE", label: "Peru" },
  { value: "PH", label: "Philippines" },
  { value: "PL", label: "Poland" },
  { value: "PT", label: "Portugal" },
  { value: "PR", label: "Puerto Rico" },
  { value: "QA", label: "Qatar" },
  { value: "RO", label: "Romania" },
  { value: "RU", label: "Russia" },
  { value: "RW", label: "Rwanda" },
  { value: "SA", label: "Saudi Arabia" },
  { value: "SN", label: "Senegal" },
  { value: "RS", label: "Serbia" },
  { value: "SG", label: "Singapore" },
  { value: "SK", label: "Slovakia" },
  { value: "SI", label: "Slovenia" },
  { value: "SO", label: "Somalia" },
  { value: "ZA", label: "South Africa" },
  { value: "KR", label: "South Korea" },
  { value: "ES", label: "Spain" },
  { value: "LK", label: "Sri Lanka" },
  { value: "SD", label: "Sudan" },
  { value: "SE", label: "Sweden" },
  { value: "CH", label: "Switzerland" },
  { value: "TW", label: "Taiwan" },
  { value: "TJ", label: "Tajikistan" },
  { value: "TZ", label: "Tanzania" },
  { value: "TH", label: "Thailand" },
  { value: "TN", label: "Tunisia" },
  { value: "TR", label: "Turkey" },
  { value: "TM", label: "Turkmenistan" },
  { value: "UG", label: "Uganda" },
  { value: "UA", label: "Ukraine" },
  { value: "AE", label: "UAE" },
  { value: "GB", label: "United Kingdom" },
  { value: "US", label: "United States" },
  { value: "UY", label: "Uruguay" },
  { value: "UZ", label: "Uzbekistan" },
  { value: "VE", label: "Venezuela" },
  { value: "VN", label: "Vietnam" },
  { value: "YE", label: "Yemen" },
  { value: "ZM", label: "Zambia" },
  { value: "ZW", label: "Zimbabwe" },
];

/**
 * Parse a target_country string into an array of codes.
 * Handles: "PK", "PK,US,AE", "WORLDWIDE"
 */
export function parseCountries(value: string): string[] {
  if (!value || value === "WORLDWIDE") return [];
  return value.split(",").map((c) => c.trim()).filter(Boolean);
}

/** Convert selected codes back to storage string */
export function serializeCountries(codes: string[], isWorldwide: boolean): string {
  if (isWorldwide) return "WORLDWIDE";
  return codes.join(",");
}

/** Get display label */
export function countryLabel(value: string): string {
  if (!value) return "Not set";
  if (value === "WORLDWIDE") return "Worldwide";
  const codes = parseCountries(value);
  if (codes.length === 1) return ALL_COUNTRIES.find((c) => c.value === codes[0])?.label || codes[0];
  return `${codes.length} countries`;
}

export function CountryPicker({
  value,
  onChange,
  compact = false,
}: {
  value: string;
  onChange: (value: string) => void;
  compact?: boolean;
}) {
  const selected = parseCountries(value);
  const isWorldwide = value === "WORLDWIDE";
  const [search, setSearch] = useState("");

  const toggle = (code: string) => {
    let next: string[];
    if (selected.includes(code)) {
      next = selected.filter((c) => c !== code);
    } else {
      next = [...selected, code];
    }
    onChange(serializeCountries(next, false));
  };

  const toggleWorldwide = () => {
    if (isWorldwide) {
      onChange("US");
    } else {
      onChange("WORLDWIDE");
    }
  };

  const filtered = search
    ? ALL_COUNTRIES.filter((c) =>
        c.label.toLowerCase().includes(search.toLowerCase()) ||
        c.value.toLowerCase().includes(search.toLowerCase())
      )
    : ALL_COUNTRIES;

  const inputClass = compact
    ? "w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-xs placeholder-gray-600 focus:outline-none focus:border-emerald-500/40 transition-all"
    : "w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-white text-sm placeholder-gray-600 focus:outline-none focus:border-violet-500/40 transition-all";

  return (
    <div className="space-y-2">
      {/* Worldwide toggle */}
      <button
        type="button"
        onClick={toggleWorldwide}
        className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl border text-left transition-all ${
          isWorldwide
            ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
            : "bg-white/[0.02] border-white/[0.06] text-gray-400 hover:border-white/[0.12]"
        }`}
      >
        <Globe className="w-3.5 h-3.5" />
        <span className={`${compact ? "text-xs" : "text-sm"} font-medium`}>Worldwide (All Countries)</span>
        {isWorldwide && <Check className="w-3.5 h-3.5 ml-auto" />}
      </button>

      {!isWorldwide && (
        <>
          {/* Selected tags */}
          {selected.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {selected.map((code) => {
                const country = ALL_COUNTRIES.find((c) => c.value === code);
                return (
                  <span
                    key={code}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-violet-500/10 border border-violet-500/20 text-violet-300 text-[11px]"
                  >
                    {country?.label || code}
                    <button
                      type="button"
                      onClick={() => toggle(code)}
                      className="hover:text-white transition-colors"
                    >
                      <X className="w-2.5 h-2.5" />
                    </button>
                  </span>
                );
              })}
            </div>
          )}

          {/* Search + country list */}
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search countries..."
            className={inputClass}
          />
          <div className={`${compact ? "max-h-[120px]" : "max-h-[160px]"} overflow-y-auto space-y-0.5 rounded-xl border border-white/[0.06] bg-white/[0.01] p-1`}>
            {filtered.map((c) => {
              const isSelected = selected.includes(c.value);
              return (
                <button
                  type="button"
                  key={c.value}
                  onClick={() => toggle(c.value)}
                  className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition-all ${
                    isSelected
                      ? "bg-violet-500/10 text-violet-300"
                      : "text-gray-400 hover:bg-white/[0.04] hover:text-gray-200"
                  }`}
                >
                  <div
                    className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-all ${
                      isSelected ? "bg-violet-500 border-violet-500" : "border-white/[0.15] bg-white/[0.03]"
                    }`}
                  >
                    {isSelected && <Check className="w-2.5 h-2.5 text-white" />}
                  </div>
                  <span className={compact ? "text-xs" : "text-xs"}>{c.label}</span>
                  <span className="text-[10px] text-gray-600 ml-auto">{c.value}</span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
