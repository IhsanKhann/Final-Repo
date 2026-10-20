import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { AlertCircle, CheckCircle, RefreshCw, Send, ShieldAlert, Sparkles, UserCheck } from 'lucide-react';

export default function ReviewQueue() {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState(null);
  const [editValues, setEditValues] = useState({});
  const [actionMessage, setActionMessage] = useState(null);
  const [submittingId, setSubmittingId] = useState(null);

  const fetchQueue = async () => {
    setLoading(true);
    try {
      const res = await axios.get('/api/review-queue');
      setRecords(res.data.records || []);
    } catch (err) {
      console.error('Failed to load review queue:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  const handleStartEdit = (record) => {
    setEditingId(record.id);
    setEditValues({
      corrected_value: record.standardized_value || '',
      corrected_unit: record.unit || '',
      analyst_notes: `Confirmed by analyst - resolved ambiguity for ${record.field_name}`
    });
  };

  const handleApprove = async (recordId) => {
    setSubmittingId(recordId);
    try {
      const payload = editValues[recordId] || {
        corrected_value: editValues.corrected_value,
        corrected_unit: editValues.corrected_unit,
        analyst_notes: editValues.analyst_notes
      };

      const res = await axios.post(`/api/review-queue/${recordId}/approve`, payload);
      setActionMessage({
        type: 'success',
        text: `Record ${recordId} successfully corrected, approved, and streamed to BigQuery (normalized_records).`
      });

      // Update state locally
      setRecords(prev => prev.map(item => item.id === recordId ? { ...item, status: 'approved', requires_human_review: false } : item));
      setEditingId(null);
      setTimeout(() => setActionMessage(null), 5000);
    } catch (err) {
      console.error('Error approving record:', err);
      setActionMessage({
        type: 'error',
        text: `Approval failed: ${err.response?.data?.error || err.message}`
      });
    } finally {
      setSubmittingId(null);
    }
  };

  const pendingCount = records.filter(r => r.requires_human_review !== false && r.status !== 'approved').length;

  return (
    <div className="glass-panel rounded-2xl p-6 border border-slate-800 shadow-2xl">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-6 border-b border-slate-800/80">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-white flex items-center gap-2">
                Analyst Review Queue
                <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  {pendingCount} Pending Attention
                </span>
              </h2>
              <p className="text-sm text-slate-400">
                Human-in-the-loop feedback mechanism for ambiguous extractions and rate sheet anomalies
              </p>
            </div>
          </div>
        </div>

        <button
          onClick={fetchQueue}
          disabled={loading}
          className="flex items-center gap-2 px-3.5 py-2 text-xs font-medium text-slate-300 bg-slate-800/80 hover:bg-slate-700/80 rounded-lg border border-slate-700 transition"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-cyan-400' : ''}`} />
          Refresh Queue
        </button>
      </div>

      {actionMessage && (
        <div className={`mt-4 p-3.5 rounded-xl text-sm flex items-center gap-2.5 border ${
          actionMessage.type === 'success' 
            ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' 
            : 'bg-rose-500/10 border-rose-500/30 text-rose-300'
        }`}>
          {actionMessage.type === 'success' ? <CheckCircle className="w-4 h-4 shrink-0" /> : <AlertCircle className="w-4 h-4 shrink-0" />}
          {actionMessage.text}
        </div>
      )}

      {loading ? (
        <div className="py-16 text-center text-slate-400">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto text-cyan-500 mb-3" />
          <p className="text-sm">Fetching BigQuery Review Queue records...</p>
        </div>
      ) : records.length === 0 ? (
        <div className="py-16 text-center">
          <CheckCircle className="w-10 h-10 text-emerald-400 mx-auto mb-3 opacity-80" />
          <h3 className="text-base font-semibold text-slate-200">Review Queue is Clear!</h3>
          <p className="text-sm text-slate-500 mt-1 max-w-sm mx-auto">
            All document extractions have met the >= 0.85 confidence threshold and passed automated business rules.
          </p>
        </div>
      ) : (
        <div className="space-y-4 mt-6">
          {records.map((item) => {
            const isApproved = item.status === 'approved' || item.requires_human_review === false;
            const isEditing = editingId === item.id;

            return (
              <div
                key={item.id}
                className={`p-5 rounded-xl border transition-all ${
                  isApproved
                    ? 'bg-slate-900/40 border-slate-800/50 opacity-60'
                    : 'bg-slate-900/90 border-slate-800 hover:border-amber-500/30 shadow-lg'
                }`}
              >
                <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
                  <div className="space-y-1.5 max-w-2xl">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-cyan-400 border border-slate-700">
                        {item.document_id}
                      </span>
                      <span className="text-xs font-semibold text-white px-2 py-0.5 rounded bg-slate-800/80">
                        Field: <code className="text-amber-300">{item.field_name}</code>
                      </span>
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-rose-500/10 border border-rose-500/20 text-rose-300">
                        Confidence: {(item.confidence * 100).toFixed(0)}%
                      </span>
                      {isApproved && (
                        <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 flex items-center gap-1">
                          <CheckCircle className="w-3 h-3" /> Approved to BigQuery
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs pt-2">
                      <div>
                        <span className="text-slate-400">Raw Extracted Value: </span>
                        <span className="font-mono text-slate-200 bg-slate-800/80 px-1.5 py-0.5 rounded">
                          "{item.raw_value}"
                        </span>
                      </div>
                      <div>
                        <span className="text-slate-400">Proposed Standardized: </span>
                        <span className="font-mono text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-800/30">
                          {item.standardized_value} {item.unit ? `(${item.unit})` : ''}
                        </span>
                      </div>
                    </div>

                    <div className="pt-1.5 text-xs text-amber-300/90 flex items-start gap-1.5">
                      <AlertCircle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                      <span><strong>Ambiguity Reason:</strong> {item.reasoning}</span>
                    </div>
                  </div>

                  {!isApproved && (
                    <div className="flex items-center gap-2 shrink-0">
                      {!isEditing ? (
                        <button
                          onClick={() => handleStartEdit(item)}
                          className="px-3.5 py-2 text-xs font-semibold bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded-lg transition flex items-center gap-1.5"
                        >
                          <UserCheck className="w-3.5 h-3.5" /> Correct & Approve
                        </button>
                      ) : null}
                    </div>
                  )}
                </div>

                {isEditing && (
                  <div className="mt-4 pt-4 border-t border-slate-800 grid grid-cols-1 md:grid-cols-3 gap-3 bg-slate-950/50 p-4 rounded-lg">
                    <div>
                      <label className="block text-xs font-medium text-slate-300 mb-1">Corrected Value</label>
                      <input
                        type="text"
                        value={editValues.corrected_value}
                        onChange={(e) => setEditValues({ ...editValues, corrected_value: e.target.value })}
                        className="w-full text-xs font-mono bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-white focus:outline-none focus:border-cyan-500"
                        placeholder="e.g. 0.145"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-300 mb-1">Unit / Currency</label>
                      <input
                        type="text"
                        value={editValues.corrected_unit}
                        onChange={(e) => setEditValues({ ...editValues, corrected_unit: e.target.value })}
                        className="w-full text-xs font-mono bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-white focus:outline-none focus:border-cyan-500"
                        placeholder="e.g. percentage, USD, kg"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-slate-300 mb-1">Analyst Notes</label>
                      <input
                        type="text"
                        value={editValues.analyst_notes}
                        onChange={(e) => setEditValues({ ...editValues, analyst_notes: e.target.value })}
                        className="w-full text-xs bg-slate-900 border border-slate-700 rounded-md px-2.5 py-1.5 text-white focus:outline-none focus:border-cyan-500"
                        placeholder="Resolution justification"
                      />
                    </div>
                    <div className="md:col-span-3 flex justify-end gap-2 pt-2">
                      <button
                        onClick={() => setEditingId(null)}
                        className="px-3 py-1.5 text-xs text-slate-400 hover:text-white"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleApprove(item.id)}
                        disabled={submittingId === item.id}
                        className="px-4 py-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition flex items-center gap-1.5 shadow-md shadow-emerald-950"
                      >
                        <Send className="w-3.5 h-3.5" />
                        {submittingId === item.id ? 'Streaming to BigQuery...' : 'Approve & Stream to BigQuery'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
