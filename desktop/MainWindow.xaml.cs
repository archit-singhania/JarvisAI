using System.Windows;
using System.Windows.Input;
using System.Windows.Media.Animation;
using System.ComponentModel;

namespace JarvisAI;

public partial class MainWindow : Window
{
    public MainWindow()
    {
        InitializeComponent();
        if(DataContext is MainViewModel vm)vm.PropertyChanged+=AnimateSection;
        Closed += (_, _) => (DataContext as MainViewModel)?.Dispose();
    }

    private void AnimateSection(object? sender,PropertyChangedEventArgs args)
    {
        if(args.PropertyName!=nameof(MainViewModel.Section)||sender is not MainViewModel vm||vm.ReduceMotion||!SystemParameters.ClientAreaAnimation)return;
        MainContent.BeginAnimation(OpacityProperty,new DoubleAnimation(0.45,1,TimeSpan.FromMilliseconds(240)){EasingFunction=new QuadraticEase{EasingMode=EasingMode.EaseOut}});
    }

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
            WindowState = WindowState == WindowState.Maximized
                ? WindowState.Normal : WindowState.Maximized;
        else
            DragMove();
    }

    private void Minimize_Click(object sender, RoutedEventArgs e) =>
        WindowState = WindowState.Minimized;

    private void Close_Click(object sender, RoutedEventArgs e) =>
        Application.Current.Shutdown();

    private void InputBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && !Keyboard.IsKeyDown(Key.LeftShift))
        {
            if (DataContext is MainViewModel vm)
                vm.SendTextCommand.Execute(null);
            e.Handled = true;
        }
    }
}
