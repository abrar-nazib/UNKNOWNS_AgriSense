"use client";

// Cascading Division -> District -> Upazila picker.
// Source of truth: src/data/bd-geocodes.json (crawled from CZIS /services/*),
// so every selection carries the real CZIS/BBS code (e.g. upazila 508194) that
// the agent later feeds straight into CZIS + weather tools. Codes are NEVER
// free-typed — this is the guard against the "HTTP 200 + null" bad-geocode trap.

import geo from "@/data/bd-geocodes.json";
import type { Address } from "@/lib/types";

interface Upazila {
  name: string;
  code: string;
}
interface District {
  name: string;
  code: string;
  upazilas: Upazila[];
}
interface Division {
  name: string;
  code: string;
  districts: District[];
}

const DIVISIONS = (geo as { divisions: Division[] }).divisions;

export const EMPTY_ADDRESS: Address = {
  division_name: "",
  division_code: "",
  district_name: "",
  district_code: "",
  upazila_name: "",
  upazila_code: "",
};

interface Props {
  value: Address;
  onChange: (next: Address) => void;
  onBlur?: () => void;
  error?: string;
}

function Select({
  label,
  value,
  onChange,
  onBlur,
  disabled,
  placeholder,
  options,
}: {
  label: string;
  value: string;
  onChange: (code: string) => void;
  onBlur?: () => void;
  disabled?: boolean;
  placeholder: string;
  options: { name: string; code: string }[];
}) {
  const id = label.toLowerCase().replace(/\s+/g, "-");
  return (
    <div className="flex flex-1 flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-text-primary">
        {label}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        className="w-full rounded-xl border border-border bg-surface px-3.5 py-2.5 text-text-primary outline-none transition focus:ring-2 focus:ring-primary-400 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
      >
        <option value="">{placeholder}</option>
        {options.map((o) => (
          <option key={o.code} value={o.code}>
            {o.name}
          </option>
        ))}
      </select>
    </div>
  );
}

export function AddressPicker({ value, onChange, onBlur, error }: Props) {
  const division = DIVISIONS.find((d) => d.code === value.division_code);
  const district = division?.districts.find(
    (z) => z.code === value.district_code,
  );

  const onDivision = (code: string) => {
    const d = DIVISIONS.find((x) => x.code === code);
    // Changing the division invalidates district + upazila — reset them.
    onChange({
      ...EMPTY_ADDRESS,
      division_name: d?.name ?? "",
      division_code: d?.code ?? "",
    });
  };

  const onDistrict = (code: string) => {
    const z = division?.districts.find((x) => x.code === code);
    onChange({
      division_name: value.division_name,
      division_code: value.division_code,
      district_name: z?.name ?? "",
      district_code: z?.code ?? "",
      upazila_name: "",
      upazila_code: "",
    });
  };

  const onUpazila = (code: string) => {
    const u = district?.upazilas.find((x) => x.code === code);
    onChange({
      ...value,
      upazila_name: u?.name ?? "",
      upazila_code: u?.code ?? "",
    });
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 sm:flex-row">
        <Select
          label="Division"
          placeholder="Select division"
          value={value.division_code}
          onChange={onDivision}
          onBlur={onBlur}
          options={DIVISIONS}
        />
        <Select
          label="District"
          placeholder={division ? "Select district" : "Select division first"}
          value={value.district_code}
          onChange={onDistrict}
          onBlur={onBlur}
          disabled={!division}
          options={division?.districts ?? []}
        />
      </div>
      <Select
        label="Upazila"
        placeholder={district ? "Select upazila" : "Select district first"}
        value={value.upazila_code}
        onChange={onUpazila}
        onBlur={onBlur}
        disabled={!district}
        options={district?.upazilas ?? []}
      />
      {error && <p className="text-xs text-status-error">{error}</p>}
    </div>
  );
}
