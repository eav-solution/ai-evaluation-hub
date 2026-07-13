"use client";

import {useEffect, useRef, useState} from "react";

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder,
  disabled,
}: {
  options: string[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeWhenOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeWhenOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeWhenOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const filtered = query
    ? options.filter((option) => option.toLowerCase().includes(query.toLowerCase()))
    : options;
  return (
    <div className="searchable-select" ref={rootRef}>
      <button
        type="button"
        className="searchable-trigger"
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        onClick={() => {
          if (!open) setQuery("");
          setOpen(!open);
        }}
      >
        <span>{value || placeholder || "Select model"}</span>
        <span aria-hidden="true">⌄</span>
      </button>
      {open && <div className="searchable-menu">
        <input
          autoFocus
          type="search"
          role="searchbox"
          aria-label="Search models"
          value={query}
          placeholder="Search models"
          onChange={(event) => setQuery(event.target.value)}
        />
        {filtered.length > 0 ? (
          <ul className="searchable-options" role="listbox">
            {filtered.map((option) => (
              <li
                key={option}
                role="option"
                aria-selected={option === value}
                tabIndex={0}
                onClick={() => {
                  onChange(option);
                  setOpen(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onChange(option);
                    setOpen(false);
                  }
                }}
              >
                {option}
              </li>
            ))}
          </ul>
        ) : <p className="searchable-empty">No matching models</p>}
      </div>}
    </div>
  );
}
