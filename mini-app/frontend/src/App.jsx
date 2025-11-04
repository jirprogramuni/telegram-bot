import React, { useState, useEffect } from 'react';
import { init, useLaunchParams } from '@telegram-apps/sdk-react';
import Form from './Form.jsx';
import Admin from './Admin.jsx';

const App = () => {
  const [isAdmin, setIsAdmin] = useState(false);
  const launchParams = useLaunchParams();

  useEffect(() => {
    init();
    const user = launchParams.initData.user;
    if (user && user.id === parseInt(process.env.ADMIN_TELEGRAM_ID || '476747112')) {
      setIsAdmin(true);
    }
  }, []);

  return (
    <div className="container">
      <h1>Учёт смен</h1>
      <Form />
      {isAdmin && <Admin />}
    </div>
  );
};

export default App;