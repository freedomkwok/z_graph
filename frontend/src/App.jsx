import MainLayout from "./MainLayout";
import { TaskStoreProvider } from "./taskStore";

function App() {
  return (
    <TaskStoreProvider>
      <MainLayout />
    </TaskStoreProvider>
  );
}

export default App;
