import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createAssistantApi } from './api';
import { App } from './App';
import './styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('Missing application root');
void createAssistantApi().then((api) => {
  createRoot(root).render(<StrictMode><App api={api} /></StrictMode>);
});
