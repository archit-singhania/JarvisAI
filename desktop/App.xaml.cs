using System.Globalization;
using System.Windows;
using System.Windows.Data;
using System.Windows.Media;
using Microsoft.Win32;
namespace JarvisAI;
public partial class App : Application {}
public sealed class SectionVisibilityConverter:IValueConverter
{
    public object Convert(object value,Type targetType,object parameter,CultureInfo culture){var choices=(parameter?.ToString()??"").Split('|');var section=value?.ToString()??"";var match=choices.Contains(section);if(choices[0].StartsWith('!'))match=section!=choices[0][1..];return match?Visibility.Visible:Visibility.Collapsed;}
    public object ConvertBack(object value,Type targetType,object parameter,CultureInfo culture)=>Binding.DoNothing;
}
public static class ThemeManager
{
    public static void Apply(string theme)
    {
        bool light=theme=="light";
        if(theme=="system")light=Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize","AppsUseLightTheme",0) is int value&&value==1;
        var colors=light?new Dictionary<string,string>{{"BgDeep","#F5F4F8"},{"BgPanel","#FDFCFF"},{"BgCard","#ECEAF3"},{"TextPrimary","#242136"},{"TextSecondary","#696478"},{"AccentCyan","#705AC3"},{"BorderBrush","#DDD8E8"}}:new Dictionary<string,string>{{"BgDeep","#10111B"},{"BgPanel","#191B28"},{"BgCard","#232535"},{"TextPrimary","#F3F1FA"},{"TextSecondary","#A19DB2"},{"AccentCyan","#B6A8FF"},{"BorderBrush","#343345"}};
        foreach(var item in colors)Application.Current.Resources[item.Key]=new SolidColorBrush((Color)ColorConverter.ConvertFromString(item.Value));
    }
}
