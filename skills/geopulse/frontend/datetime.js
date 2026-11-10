const formatterCache = new Map();

function formatter(timeZone) {
  if (!formatterCache.has(timeZone)) {
    try {
      formatterCache.set(timeZone, new Intl.DateTimeFormat("en-US", {
        timeZone, year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hourCycle: "h23",
      }));
    } catch {
      throw new Error(`无效项目时区：${timeZone}`);
    }
  }
  return formatterCache.get(timeZone);
}

function partsAt(value, timeZone) {
  const parts = Object.fromEntries(formatter(timeZone).formatToParts(value)
    .filter((part) => part.type !== "literal").map((part) => [part.type, Number(part.value)]));
  return [parts.year, parts.month, parts.day, parts.hour, parts.minute];
}

function stamp(parts) {
  const [year, month, day, hour, minute] = parts;
  const date = new Date(Date.UTC(year, month - 1, day, hour, minute));
  if (year >= 0 && year < 100) date.setUTCFullYear(year);
  return date.getTime();
}

export function toDateTimeLocal(value, timeZone) {
  if (!value) return "";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const [year, month, day, hour, minute] = partsAt(date, timeZone);
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function fromDateTimeLocal(value, timeZone) {
  const match = /^(\d{4,})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) throw new Error("请填写完整的本地日期和时间");
  const desired = match.slice(1).map(Number);
  const [year, month, day, hour, minute] = desired;
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59) {
    throw new Error("本地日期或时间无效");
  }
  const desiredStamp = stamp(desired);
  const roundTrip = new Date(desiredStamp);
  if (roundTrip.getUTCFullYear() !== year || roundTrip.getUTCMonth() + 1 !== month || roundTrip.getUTCDate() !== day
    || roundTrip.getUTCHours() !== hour || roundTrip.getUTCMinutes() !== minute) {
    throw new Error("本地日期或时间无效");
  }
  const offsets = new Set();
  for (const delta of [-172800000, -86400000, 0, 86400000, 172800000]) {
    const instant = new Date(desiredStamp + delta);
    offsets.add(stamp(partsAt(instant, timeZone)) - instant.getTime());
  }
  const candidates = [...offsets].map((offset) => desiredStamp - offset)
    .filter((candidate) => stamp(partsAt(new Date(candidate), timeZone)) === desiredStamp);
  if (!candidates.length) throw new Error(`${timeZone} 在该日期存在夏令时跳时，请选择另一个本地时间`);
  if (candidates.length > 1) throw new Error(`${timeZone} 在该日期存在重复本地时间，请避开这个时段`);
  return new Date(candidates[0]).toISOString();
}

export function dateInTimezone(timeZone, value = new Date()) {
  return toDateTimeLocal(value, timeZone).slice(0, 10);
}
