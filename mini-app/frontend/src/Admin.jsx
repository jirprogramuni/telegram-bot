import React, { useState, useEffect } from 'react';
import { Button } from '@telegram-apps/telegram-ui';
import { useLaunchParams } from '@telegram-apps/sdk-react';
import DatePicker from 'react-datepicker';

const Admin = () => {
  const [shifts, setShifts] = useState([]);
  const [editing, setEditing] = useState(null);
  const launchParams = useLaunchParams();

  useEffect(() => {
    fetchShifts();
  }, []);

  const fetchShifts = async () => {
    const initData = launchParams.initDataRaw;
    const res = await fetch('/api/admin/list', { headers: { 'X-Telegram-Init-Data': initData } });
    const data = await res.json();
    setShifts(data);
  };

  const handleEdit = (shift) => {
    setEditing({ ...shift, date: new Date(shift.date.split('.').reverse().join('-')) });
  };

  const handleUpdate = async () => {
    const initData = launchParams.initDataRaw;
    await fetch('/api/admin/update', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData },
      body: JSON.stringify(editing),
    });
    setEditing(null);
    fetchShifts();
  };

  return (
    <div className="admin-list">
      <h2>Админ панель</h2>
      {shifts.map((shift, idx) => (
        <div key={idx} className="shift-item">
          <p>@{shift.username} ({shift.id})</p>
          <p>Дата: {shift.date}</p>
          <p>Заведение: {shift.place}</p>
          <p>Смена: {shift.start} - {shift.end}</p>
          <Button onClick={() => handleEdit(shift)}>✏️ Редактировать</Button>
        </div>
      ))}
      {editing && (
        <div>
          <h3>Редактировать</h3>
          <DatePicker selected={editing.date} onChange={(d) => setEditing({ ...editing, date: d })} />
          <select value={editing.place} onChange={(e) => setEditing({ ...editing, place: e.target.value })}>
            {places.map(p => <option key={p}>{p}</option>)}
          </select>
          <input type="time" value={editing.start} onChange={(e) => setEditing({ ...editing, start: e.target.value })} />
          <input type="time" value={editing.end} onChange={(e) => setEditing({ ...editing, end: e.target.value })} />
          <Button onClick={handleUpdate}>Сохранить</Button>
          <Button onClick={() => setEditing(null)}>Отмена</Button>
        </div>
      )}
    </div>
  );
};

export default Admin;