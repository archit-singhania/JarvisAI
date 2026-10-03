using System;
using System.Globalization;

namespace JarvisAI;

public static class ReminderClock
{
    public static string? Suggest(string timezone, DateTimeOffset now)
    {
        try
        {
            var zone = TimeZoneInfo.FindSystemTimeZoneById(timezone);
            return TimeZoneInfo.ConvertTime(now.AddHours(1), zone)
                .ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
        }
        catch (TimeZoneNotFoundException) { return null; }
        catch (InvalidTimeZoneException) { return null; }
        catch (ArgumentException) { return null; }
    }
}
