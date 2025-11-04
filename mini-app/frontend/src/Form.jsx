import React, { useState } from 'react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import { Button } from '@telegram-apps/telegram-ui';
import { useLaunchParams } from '@telegram-apps/sdk-react';

const places = ['КУЧИНО', 'РЕУТОВ (Победы)', 'РЕУТОВ (Юбилейный)', 'ЛЕНИНА', 'НЯМС'];

const Form = () => {
  const [date, setDate] = useState(new Date());
  const [place, setPlace] = useState(places[0]);
  const [startTime, setStartTime] = useState('09:00');
  const [endTime, setEndTime] = useState('22:00');
  const launchParams = useLaunchParams();

  const handleSubmit = async () => {
    const payload = { date: date.toISOString(), place, startTime, endTime };
    const initData = launchParams.initDataRaw;

    try {
      const res = await fetch('/api/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Telegram-Init-Data': initData },
        body: JSON.stringify(payload),
      });
      if (res.ok) alert('Смена отправлена!');
    } catch (err) {
      alert('Ошибка отправки');
    }
  };

  return (
    <div>
      <div className="input">
        <label>Дата смены:</label>
        <DatePicker selected={date} onChange={setDate} dateFormat="dd.MM.yyyy" />
      </div>
      <div className="input">
        <label>Заведение:</label>
        <select value={place} onChange={(e) => setPlace(e.target.value)}>
          {places.map(p => <option key={p}>{p}</option>)}
        </select>
      </div>
      <div className="input">
        <label>Начало:</label>
        <input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
      </div>
      <div className="input">
        <label>Конец:</label>
        <input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
      </div>
      <Button onClick={handleSubmit}>Отправить</Button>
    </div>
  );
};

export default Form;