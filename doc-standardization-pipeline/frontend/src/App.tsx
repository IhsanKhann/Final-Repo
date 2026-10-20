import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ToastProvider, UndoProvider, PackProvider } from './context/AppContext';
import { AppShell } from './components/layout/AppShell';
import { ToastContainer, UndoBar } from './components/ui/Overlays';

// Pages
import { HomePage } from './pages/HomePage';
import { UploadPage } from './pages/UploadPage';
import { BatchesPage } from './pages/BatchesPage';
import { ReviewPage } from './pages/ReviewPage';
import { ReviewQueuePage } from './pages/ReviewQueuePage';
import { DatasetPage } from './pages/DatasetPage';
import { SchemaPage } from './pages/SchemaPage';
import { InsightsPage } from './pages/InsightsPage';
import { HealthPage } from './pages/HealthPage';
import { SettingsPage } from './pages/SettingsPage';
import { HelpPage } from './pages/HelpPage';

export function App() {
  return (
    <ToastProvider>
      <UndoProvider>
        <PackProvider>
          <BrowserRouter>
            <AppShell>
              <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/upload" element={<UploadPage />} />
                <Route path="/batches" element={<BatchesPage />} />
                <Route path="/review" element={<ReviewPage />} />
                <Route path="/review-queue" element={<ReviewQueuePage />} />
                <Route path="/dataset" element={<DatasetPage />} />
                <Route path="/schema" element={<SchemaPage />} />
                <Route path="/insights" element={<InsightsPage />} />
                <Route path="/health" element={<HealthPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/help" element={<HelpPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AppShell>
            <ToastContainer />
            <UndoBar />
          </BrowserRouter>
        </PackProvider>
      </UndoProvider>
    </ToastProvider>
  );
}

export default App;
