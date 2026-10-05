using System.Globalization;
using System.Windows;
using System.Windows.Data;
using System.Windows.Media;
using Microsoft.Win32;
namespace JarvisAI;
public partial class App : Application
{
    public App()
    {
        AppDomain.CurrentDomain.UnhandledException+=(_,args)=>SmokeLog(args.ExceptionObject.ToString()??"Startup error");
        DispatcherUnhandledException+=(_,args)=>SmokeLog(args.Exception.ToString());
    }
    private static void SmokeLog(string error)
    {
        var output=Environment.GetEnvironmentVariable("WEDNESDAY_SMOKE_LOG");
        if(output is not null)File.WriteAllText(output,error);
    }
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var audioCheck=e.Args.FirstOrDefault(a=>a.StartsWith("--audio-check="));
        if(audioCheck is not null)
        {
            ShutdownMode=ShutdownMode.OnExplicitShutdown;
            try
            {
                var directory=Path.GetFullPath(audioCheck[14..]);var checks=new List<object>();
                foreach(var format in new[]{"wav","mp3"})
                {
                    using var input=File.OpenRead(Path.Combine(directory,"acceptance-tone."+format));
                    using var reader=Services.AudioService.Decode(input,format);
                    var samples=new byte[8192];long decoded=0;int read;
                    while((read=reader.Read(samples,0,samples.Length))>0)decoded+=read;
                    if(decoded==0)throw new InvalidDataException("Audio decoding returned no samples.");
                    checks.Add(new{format,decodedBytes=decoded,sampleRate=reader.WaveFormat.SampleRate,channels=reader.WaveFormat.Channels});
                }
                File.WriteAllText(Path.Combine(directory,"native-audio-acceptance.json"),System.Text.Json.JsonSerializer.Serialize(new{passed=true,syntheticToneFixture=true,checks},new System.Text.Json.JsonSerializerOptions{WriteIndented=true}));Shutdown(0);
            }
            catch(Exception error){SmokeLog(error.ToString());Shutdown(1);}
            return;
        }
        var output=e.Args.FirstOrDefault(a=>a.StartsWith("--smoke="));
        if(output is null){new MainWindow().Show();return;}
        ShutdownMode=ShutdownMode.OnExplicitShutdown;
        try
        {
            var window=new MainWindow();await Task.Delay(1600);
            var requestedSection=e.Args.FirstOrDefault(a=>a.StartsWith("--smoke-section="))?[16..];
            if(requestedSection is "Preferences" or "Memory" or "Knowledge" or "Reminders" or "Tools" or "Workflows")
            {
                if(window.DataContext is MainViewModel vm)await vm.OpenSectionCommand.ExecuteAsync(requestedSection);
            }
            var visual=(FrameworkElement)window.Content;
            visual.Measure(new Size(1220,840));visual.Arrange(new Rect(0,0,1220,840));visual.UpdateLayout();
            var target=new System.Windows.Media.Imaging.RenderTargetBitmap(1220,840,96,96,PixelFormats.Pbgra32);
            var backdrop=new DrawingVisual();using(var drawing=backdrop.RenderOpen())drawing.DrawRectangle((Brush)Resources["BgDeep"],null,new Rect(0,0,1220,840));target.Render(backdrop);
            target.Render(visual);
            var encoder=new System.Windows.Media.Imaging.PngBitmapEncoder();encoder.Frames.Add(System.Windows.Media.Imaging.BitmapFrame.Create(target));
            var path=Path.GetFullPath(output[8..]);Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using(var file=File.Create(path))encoder.Save(file);
            (window.DataContext as MainViewModel)?.Dispose();Shutdown(0);
        }
        catch(Exception error){SmokeLog(error.ToString());Shutdown(1);}
    }
}
public sealed class EmptyVisibilityConverter:IValueConverter
{
    public object Convert(object value,Type targetType,object parameter,CultureInfo culture)=>value is int count&&count==0?Visibility.Visible:Visibility.Collapsed;
    public object ConvertBack(object value,Type targetType,object parameter,CultureInfo culture)=>Binding.DoNothing;
}
public sealed class SectionVisibilityConverter:IValueConverter
{
    public object Convert(object value,Type targetType,object parameter,CultureInfo culture){var choices=(parameter?.ToString()??"").Split('|');var section=value?.ToString()??"";var match=choices.Contains(section);if(choices[0].StartsWith('!'))match=section!=choices[0][1..];return match?Visibility.Visible:Visibility.Collapsed;}
    public object ConvertBack(object value,Type targetType,object parameter,CultureInfo culture)=>Binding.DoNothing;
}
public static class ThemeManager
{
    public static void Apply(string theme,bool reduceTransparency=false,bool highContrastPreference=false)
    {
        if(SystemParameters.HighContrast||highContrastPreference)
        {
            var highContrast=new Dictionary<string,Brush>{{"BgDeep",SystemColors.WindowBrush},{"BgPanel",SystemColors.WindowBrush},{"BgCard",SystemColors.ControlBrush},{"TextPrimary",SystemColors.WindowTextBrush},{"TextSecondary",SystemColors.WindowTextBrush},{"AccentCyan",SystemColors.HighlightBrush},{"BorderBrush",SystemColors.WindowTextBrush}};
            foreach(var item in highContrast)Application.Current.Resources[item.Key]=item.Value;
            Application.Current.Resources["GlassPanel"]=SystemColors.WindowBrush;
            Application.Current.Resources["GlassControl"]=SystemColors.ControlBrush;
            Application.Current.Resources["GlassRim"]=SystemColors.WindowTextBrush;
            return;
        }
        bool light=theme=="light";
        if(theme=="system")light=Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize","AppsUseLightTheme",0) is int value&&value==1;
        var colors=light?new Dictionary<string,string>{{"BgDeep","#F5F4F8"},{"BgPanel","#FDFCFF"},{"BgCard","#ECEAF3"},{"TextPrimary","#242136"},{"TextSecondary","#696478"},{"AccentCyan","#705AC3"},{"BorderBrush","#DDD8E8"}}:new Dictionary<string,string>{{"BgDeep","#10111B"},{"BgPanel","#191B28"},{"BgCard","#232535"},{"TextPrimary","#F3F1FA"},{"TextSecondary","#A19DB2"},{"AccentCyan","#B6A8FF"},{"BorderBrush","#343345"}};
        foreach(var item in colors)Application.Current.Resources[item.Key]=new SolidColorBrush((Color)ColorConverter.ConvertFromString(item.Value));
        Brush Material(string opaque,string top,string baseColor) => reduceTransparency
            ? new SolidColorBrush((Color)ColorConverter.ConvertFromString(opaque))
            : new LinearGradientBrush(new GradientStopCollection {
                new((Color)ColorConverter.ConvertFromString(top),0),
                new((Color)ColorConverter.ConvertFromString(baseColor),0.45),
                new((Color)ColorConverter.ConvertFromString(baseColor),1)},new Point(0,0),new Point(1,1));
        Application.Current.Resources["GlassPanel"]=Material(colors["BgPanel"],light?"#EFFDFBFF":"#EC353347",light?"#C9F5F2FB":"#D51E202E");
        Application.Current.Resources["GlassControl"]=Material(colors["BgCard"],light?"#F6FFFFFF":"#EC454058",light?"#DBEAE5F5":"#C52D2B40");
        Application.Current.Resources["GlassRim"]=new SolidColorBrush((Color)ColorConverter.ConvertFromString(reduceTransparency?colors["BorderBrush"]:light?"#FFFFFFFF":"#88786C96"));
    }
}
