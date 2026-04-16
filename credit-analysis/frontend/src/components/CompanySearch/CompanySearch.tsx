import React, { useCallback, useEffect, useRef, useState } from "react";
import { searchCompanies, type CompanySearchResult } from "../../api/companies";

interface Props {
  onSelect: (company: CompanySearchResult) => void;
}

export function CompanySearch({ onSelect }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CompanySearchResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const search = useCallback(async (q: string) => {
    if (q.length < 1) {
      setResults([]);
      setIsOpen(false);
      return;
    }
    setLoading(true);
    try {
      const data = await searchCompanies(q, 20);
      setResults(data);
      setIsOpen(true);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(query), 300);
    return () => clearTimeout(debounceRef.current);
  }, [query, search]);

  const handleSelect = (company: CompanySearchResult) => {
    setQuery(company.name);
    setIsOpen(false);
    onSelect(company);
  };

  return (
    <div className="relative w-full max-w-lg">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setIsOpen(true)}
          placeholder="Search by company name or ticker..."
          className="w-full px-4 py-2.5 border border-gray-300 rounded-lg shadow-sm text-sm
                     focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                     bg-white"
        />
        {loading && (
          <div className="absolute right-3 top-3">
            <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          </div>
        )}
      </div>

      {isOpen && results.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-72 overflow-y-auto">
          {results.map((company) => (
            <button
              key={company.cik}
              onClick={() => handleSelect(company)}
              className="w-full px-4 py-2.5 text-left hover:bg-blue-50 flex items-center gap-3 border-b border-gray-100 last:border-0"
            >
              {company.ticker && (
                <span className="text-xs font-mono font-semibold text-blue-700 bg-blue-50 px-1.5 py-0.5 rounded min-w-[48px] text-center">
                  {company.ticker}
                </span>
              )}
              <span className="text-sm text-gray-800 truncate">{company.name}</span>
              <span className="text-xs text-gray-400 ml-auto shrink-0">CIK {company.cik}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
