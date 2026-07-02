import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import Dashboard from "./pages/Dashboard";
import Positions from "./pages/Positions";
import Activity from "./pages/Activity";
import Watchlist from "./pages/Watchlist";
import Knowledge from "./pages/Knowledge";
import Control from "./pages/Control";
import Risk from "./pages/Risk";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 2_000,
    },
  },
});

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="flex-1 ml-64 p-8 max-w-[1600px]">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/positions" element={<Positions />} />
              <Route path="/activity" element={<Activity />} />
              <Route path="/watchlist" element={<Watchlist />} />
              <Route path="/knowledge" element={<Knowledge />} />
              <Route path="/control" element={<Control />} />
              <Route path="/risk" element={<Risk />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
