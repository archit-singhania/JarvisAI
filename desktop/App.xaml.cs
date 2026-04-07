using System.Globalization;
using System.Windows.Data;

namespace JarvisAI;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var mainWindow = new MainWindow();
        mainWindow.Show();
    }
}

public class BoolToVisibilityConverter : IValueConverter {
    public object Convert(object v, Type t, object p, CultureInfo c) =>
        v is true ? Visibility.Visible : Visibility.Collapsed;
    public object ConvertBack(object v, Type t, object p, CultureInfo c) =>
        throw new NotImplementedException();
}
