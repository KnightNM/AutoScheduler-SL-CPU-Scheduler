import React from 'react';
export const number = (value, digits = 2) => value == null ? '—' : Number(value).toLocaleString('en-US', { maximumFractionDigits: digits });
export const percent = value => value == null ? '—' : `${number(value * 100)}%`;
export function Metric({ label, value, unit, note }) { return <div className="metric"><span>{label}</span><strong>{value}<small>{unit}</small></strong>{note && <p>{note}</p>}</div>; }
export function Source({ children }) { return <p className="source">Source · {children}</p>; }
export function Badge({ children, tone = '' }) { return <span className={`badge ${tone}`}>{children}</span>; }
export function ErrorNotice({ children }) { return <div className="notice error" role="alert">{children}</div>; }
export async function api(path, signal) { const response = await fetch(path, { signal }); if (!response.ok) throw new Error('Unable to load the local result. Check that the demo server is running, then retry.'); return response.json(); }
