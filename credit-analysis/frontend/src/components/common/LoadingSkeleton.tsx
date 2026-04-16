import React from "react";

export function GridSkeleton() {
  return (
    <div className="animate-pulse">
      {/* Header */}
      <div className="flex gap-2 mb-2">
        <div className="h-9 bg-navy-light rounded w-64" />
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-9 bg-navy-light rounded flex-1" />
        ))}
      </div>
      {/* Rows */}
      {[...Array(20)].map((_, i) => (
        <div key={i} className={`flex gap-2 mb-1 ${i % 5 === 0 ? "opacity-70" : ""}`}>
          <div className={`h-7 rounded w-64 ${i % 5 === 0 ? "bg-gray-300" : "bg-gray-100"}`} />
          {[...Array(6)].map((_, j) => (
            <div
              key={j}
              className={`h-7 rounded flex-1 ${i % 5 === 0 ? "bg-gray-200" : "bg-gray-50"}`}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SpinnerOverlay({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-gray-400">
      <div className="w-8 h-8 border-3 border-blue-400 border-t-transparent rounded-full animate-spin mb-3" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  );
}
