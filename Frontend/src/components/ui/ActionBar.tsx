import React from 'react';
import type { Mapping } from '../../api/types';
import { Edit3, X, Check } from 'lucide-react';
import { Spinner } from './SharedUi';

interface ActionBarProps {
  mapping: Mapping;
  onEdit: (m: Mapping) => void;
  onReject: (m: Mapping) => void;
  onAccept: (m: Mapping) => void;
  isSaving?: boolean;
}

export const ActionBar: React.FC<ActionBarProps> = ({ mapping, onEdit, onReject, onAccept, isSaving }) => {
  const acceptDisabled = mapping.status === 'missing' && !mapping.value;

  const renderIcon = (type: 'edit' | 'reject' | 'accept') => {
    if (isSaving) {
      return <Spinner size={16} />;
    }
    switch (type) {
      case 'edit':
        return <Edit3 size={16} />;
      case 'reject':
        return <X size={16} />;
      case 'accept':
        return <Check size={16} />;
    }
  };

  return (
    <div className="action-bar-container" role="group" aria-label={`Actions for ${mapping.target_field}`}>
      <button
        type="button"
        className="action-bar-btn edit"
        onClick={() => onEdit(mapping)}
        aria-label={`Edit ${mapping.target_field}`}
      >
        {renderIcon('edit')}
        Edit
        <span className="kbd-badge" aria-hidden="true">E</span>
      </button>
      <button
        type="button"
        className="action-bar-btn reject"
        onClick={() => onReject(mapping)}
        aria-label={`Reject ${mapping.target_field}`}
      >
        {renderIcon('reject')}
        Reject
        <span className="kbd-badge" aria-hidden="true">R</span>
      </button>
      <button
        type="button"
        className="action-bar-btn accept"
        onClick={() => onAccept(mapping)}
        aria-label={`Accept ${mapping.target_field}`}
        disabled={acceptDisabled}
        aria-disabled={acceptDisabled}
        title={acceptDisabled ? 'Value must be entered before accepting' : undefined}
      >
        {renderIcon('accept')}
        Accept
        <span className="kbd-badge" aria-hidden="true">A</span>
      </button>
    </div>
  );
};
