/**
 * StatusBar Component
 * Shows current processing status with animated indicator.
 */

import React from 'react';

interface StatusBarProps {
  status: string;
  isLoading: boolean;
  isError: boolean;
}

export const StatusBar: React.FC<StatusBarProps> = ({ status, isLoading, isError }) => {
  const getDotClass = () => {
    if (isError) return 'docpilot-status-dot error';
    if (isLoading) return 'docpilot-status-dot loading';
    return 'docpilot-status-dot';
  };
  
  return (
    <div className="docpilot-status">
      <span className={getDotClass()} />
      <span>{status}</span>
    </div>
  );
};
